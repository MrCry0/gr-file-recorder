"""file_recorder_sink — on-demand templated recording sink for GNU Radio.

Implements FR-01..FR-05 and FR-09..FR-12 (the headless surface). The
QT GUI button (FR-06..FR-08) is layered on top in a later phase via
the ``_on_stopped`` hook and the public ``start_recording`` /
``stop_recording`` methods.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import BinaryIO

import numpy as np
from gnuradio import gr

# --------------------------------------------------------------------- types
INPUT_DTYPES: dict[str, np.dtype] = {
    "complex": np.dtype(np.complex64),
    "float":   np.dtype(np.float32),
    "int":     np.dtype(np.int32),
    "short":   np.dtype(np.int16),
    # `byte` is unsigned to match GR's `_b` convention — see
    # CONTEXT_WINDOW.md (2026-04-28). gr.blocks.vector_source_b
    # rejects negative Python ints at construction, so anyone wiring
    # a typical SDR source into us would otherwise be stuck.
    "byte":    np.dtype(np.uint8),
}

INPUT_EXTENSIONS: dict[str, str] = {
    "complex": "fc32",
    "float":   "f32",
    "int":     "s32",
    "short":   "s16",
    "byte":    "u8",
}

BUTTON_TYPES = ("push", "toggle")
BUTTON_STYLES = ("top", "bottom")
COUNTER_STYLES = ("normal", "0-padded")

# Single-pass token regex. Alternation order matters: the {{var}} arm
# must come before the {built-in} arm so the engine never lex-splits
# "{{x}}" into a "{" plus "{x}". Single-pass substitution is also why
# we *cannot* replace tokens with str.replace() in stages — a value
# pulled in from a {{var}} that happens to contain a literal "{date}"
# would otherwise be re-expanded by the next stage.
_TOKEN_RE = re.compile(r"\{\{(\w+)\}\}|\{(date|counter|freq|type)\}")

_log = logging.getLogger("file_recorder.file_recorder_sink")


# ------------------------------------------------------------------ helpers
def _format_counter(value: int, style: str) -> str:
    """Format an int per ``counter_style``. See SPECS §2.3."""
    if style == "0-padded":
        # 3-char minimum zero pad; values >=1000 spill naturally
        return f"{value:03d}"
    if style == "normal":
        return str(value)
    raise ValueError(f"counter_style must be one of {COUNTER_STYLES}; got {style!r}")


def _resolve_template(
    template: str,
    *,
    counter: int,
    counter_style: str,
    date_format: str,
    var_source: object | None,
    now: datetime | None = None,
    type_ext: str = "",
) -> str:
    """Pure-function form of the template resolution algorithm.

    Single-pass substitution: every token is resolved in one re.sub
    call, so a value pulled in from ``{{var}}`` that happens to
    contain a literal ``{date}`` is not subsequently expanded
    (SPECS §2.4). Unknown single-brace tokens are left as-is —
    a deliberate fail-visible choice.
    """
    resolved_now = now or datetime.now()

    def _replace(match: "re.Match[str]") -> str:
        var_name, builtin = match.group(1), match.group(2)
        if var_name is not None:
            if var_source is None:
                return "undefined"
            return str(getattr(var_source, var_name, "undefined"))
        if builtin == "date":
            return resolved_now.strftime(date_format)
        if builtin == "counter":
            return _format_counter(counter, counter_style)
        if builtin == "type":
            return type_ext
        # builtin == "freq" — reserved for future use
        return "undefined"

    return _TOKEN_RE.sub(_replace, template)


# ------------------------------------------------------------------- block
class file_recorder_sink(gr.sync_block):
    """GNU Radio sink that records the input stream to disk on demand.

    All public mutators are thread-safe. The QT button hookup lives
    in a later phase; this class exposes the programmatic surface
    (``start_recording`` / ``stop_recording`` / ``is_recording``)
    that the GUI layer will drive, and the ``_on_stopped`` hook that
    Phase 4 overrides to reset the button widget.
    """

    def __init__(
        self,
        file_template: str = "recording_{date}_{counter}",
        input_type: str = "complex",
        vlen: int = 1,
        button_type: str = "toggle",
        button_style: str = "top",
        date_format: str = "%Y%m%d_%H%M%S",
        counter_start: int = 1,
        counter_step: int = 1,
        counter_style: str = "0-padded",
        record_duration: int = 0,
        max_file_size: int = 0,
        button_name: str = "",
        show_template: bool = False,
    ) -> None:
        if input_type not in INPUT_DTYPES:
            raise ValueError(
                f"input_type must be one of {sorted(INPUT_DTYPES)}; got {input_type!r}"
            )
        if button_type not in BUTTON_TYPES:
            raise ValueError(
                f"button_type must be one of {BUTTON_TYPES}; got {button_type!r}"
            )
        if button_style not in BUTTON_STYLES:
            raise ValueError(
                f"button_style must be one of {BUTTON_STYLES}; got {button_style!r}"
            )
        if counter_style not in COUNTER_STYLES:
            raise ValueError(
                f"counter_style must be one of {COUNTER_STYLES}; got {counter_style!r}"
            )
        if vlen < 1:
            raise ValueError(f"vlen must be >= 1; got {vlen}")
        if record_duration < 0:
            raise ValueError(f"record_duration must be >= 0; got {record_duration}")
        if max_file_size < 0:
            raise ValueError(f"max_file_size must be >= 0; got {max_file_size}")

        dtype = INPUT_DTYPES[input_type]
        gr.sync_block.__init__(
            self,
            name="file_recorder_sink",
            in_sig=[(dtype, vlen)] if vlen > 1 else [dtype],
            out_sig=None,
        )

        # immutable config
        self._file_template = file_template
        self._input_type = input_type
        self._vlen = vlen
        self._button_type = button_type
        self._button_style = button_style
        self._date_format = date_format
        self._counter_step = counter_step
        self._counter_style = counter_style
        self._record_duration = record_duration
        self._max_file_size = max_file_size
        self._extension = INPUT_EXTENSIONS[input_type]
        self._item_size_bytes = dtype.itemsize * vlen
        self._button_name = button_name
        self._show_template = show_template if isinstance(show_template, bool) else show_template == 'True'

        # mutable state, all guarded by _lock
        self._lock = threading.Lock()
        self._recording = False
        self._file: BinaryIO | None = None
        self._filename: str | None = None
        self._bytes_written = 0
        self._start_time: float | None = None
        self._counter = counter_start
        self._var_source: object | None = None

        # Qt widgets constructed lazily on first qwidget() call so a
        # headless construction (tests, scripts) does not require a
        # live QApplication.
        self._widget: object | None = None
        self._button: object | None = None
        self._label: object | None = None

    # ---------------------------------------------- configuration setters
    def set_top_block(self, top_block: object | None) -> None:
        """Set the source for ``{{var}}`` token resolution.

        Called once from the GRC make template after construction.
        Until set (or if set to ``None``), every ``{{var}}`` token in
        a filename template resolves to the literal string
        ``"undefined"``. No exception is ever raised for a missing
        variable — see FR-05.
        """
        with self._lock:
            self._var_source = top_block

    # ------------------------------------------------ read-only properties
    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    @property
    def current_filename(self) -> str | None:
        with self._lock:
            return self._filename

    @property
    def bytes_written(self) -> int:
        with self._lock:
            return self._bytes_written

    @property
    def counter(self) -> int:
        with self._lock:
            return self._counter

    # ---------------------------------------------- public state mutators
    def start_recording(self) -> None:
        """Begin a new recording cycle. No-op if already recording."""
        with self._lock:
            if self._recording:
                return
            self._start_recording_locked()

    def stop_recording(self) -> None:
        """End the current recording cycle. No-op if idle."""
        with self._lock:
            if not self._recording:
                return
            self._stop_recording_locked(cause="manual")

    # ------------------------------------------------- gr.sync_block API
    def work(self, input_items, output_items):
        in0 = input_items[0]
        n = len(in0)

        with self._lock:
            if not self._recording:
                # consume-and-discard: never stall the upstream pipeline
                return n

            # Invariant: recording → file is open
            assert self._file is not None
            assert self._start_time is not None

            # 1. duration cap
            if (
                self._record_duration > 0
                and (time.monotonic() - self._start_time) >= self._record_duration
            ):
                self._stop_recording_locked(cause="duration")
                return n

            write_bytes = n * self._item_size_bytes

            # 2. size cap — possibly write a truncated tail then stop
            if (
                self._max_file_size > 0
                and self._bytes_written + write_bytes >= self._max_file_size
            ):
                allowed = max(0, self._max_file_size - self._bytes_written)
                n_allowed = allowed // self._item_size_bytes
                if n_allowed > 0:
                    self._file.write(in0[:n_allowed].tobytes())
                    self._bytes_written += n_allowed * self._item_size_bytes
                self._stop_recording_locked(cause="size")
                return n

            # 3. normal path
            self._file.write(in0.tobytes())
            self._bytes_written += write_bytes
            return n

    def stop(self):
        """GR override: flowgraph is shutting down — close any open file."""
        with self._lock:
            if self._recording:
                self._stop_recording_locked(cause="flowgraph_stop")
        return True

    # ----------------------------------------- internals (caller holds lock)
    def _start_recording_locked(self) -> None:
        filename = _resolve_template(
            self._file_template,
            counter=self._counter,
            counter_style=self._counter_style,
            date_format=self._date_format,
            var_source=self._var_source,
            type_ext=self._extension,
        )

        filename = os.path.expanduser(filename)

        try:
            dirname = os.path.dirname(filename)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname, exist_ok=True)
            handle = open(filename, "wb")
        except OSError as exc:
            _log.error("failed to open %r for recording: %s", filename, exc)
            # stay IDLE; let the GUI layer (Phase 4) reset its button
            self._on_stopped(cause="open_failed")
            return

        self._file = handle
        self._filename = filename
        self._bytes_written = 0
        self._start_time = time.monotonic()
        self._recording = True
        # FR-03: counter advances on every cycle, never reset.
        self._counter += self._counter_step

        if self._label is not None:
            self._label.setText(filename)

    def _stop_recording_locked(self, *, cause: str) -> None:
        if self._file is not None:
            try:
                self._file.flush()
            finally:
                self._file.close()
        self._file = None
        self._recording = False
        self._start_time = None
        # _filename and _bytes_written are preserved for post-mortem
        # inspection until the next start.
        self._on_stopped(cause=cause)

    # ------------------------------------------------- Qt GUI integration
    @property
    def button_widget(self):
        """Return the inner QPushButton (for tests that need it)."""
        if self._button is None:
            self.qwidget()
        return self._button

    def qwidget(self):
        """Return the container widget with button and optional label.

        Lazily constructed on first call — until then no PyQt5 import
        happens, which keeps headless usage (tests, batch scripts)
        free of any Qt dependency. Caller must have a live
        ``QApplication`` before calling this; in normal GRC use the
        generated flowgraph creates one before instantiating blocks.
        """
        if self._widget is None:
            self._widget, self._button, self._label = self._make_widget()
        return self._widget

    def dock_area(self):
        """Return the Qt toolbar area corresponding to ``button_style``.

        Used by the GRC make template to decide whether the button
        sits on the top or bottom toolbar of the main window.
        """
        from PyQt5.QtCore import Qt
        return (
            Qt.TopToolBarArea if self._button_style == "top"
            else Qt.BottomToolBarArea
        )

    def _button_text(self) -> str:
        text = "Record"
        if self._button_name:
            text = f"{self._button_name} {text}"
        return text

    def _make_widget(self):
        from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

        button = QPushButton(self._button_text())
        if self._button_type == "toggle":
            button.setCheckable(True)
            button.toggled.connect(self._on_button_toggled)
        else:  # push
            button.pressed.connect(self._on_button_pressed)
            button.released.connect(self._on_button_released)

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(button)

        label: QLabel | None = None
        if self._show_template:
            label = QLabel(self._file_template)
            label.setStyleSheet("color: gray; padding-left: 4px;")
            layout.addWidget(label)

        return container, button, label

    # --- Qt slot bodies (run on the Qt event thread) -------------------
    def _on_button_toggled(self, checked: bool) -> None:
        if checked:
            self.start_recording()
        else:
            self.stop_recording()

    def _on_button_pressed(self) -> None:
        self.start_recording()

    def _on_button_released(self) -> None:
        self.stop_recording()

    # ------------------------------------------ extension hook for Qt layer
    def _on_stopped(self, *, cause: str) -> None:
        """Hook called inside ``self._lock`` after a stop transition.

        ``cause`` is one of: ``"manual"``, ``"duration"``, ``"size"``,
        ``"flowgraph_stop"``, ``"open_failed"``. When a button widget
        exists *and* the stop did not originate from a button-driven
        transition, queue a state reset onto the Qt thread so the
        widget visually matches the recording state.

        ``QueuedConnection`` is mandatory: this method runs while
        the scheduler thread holds ``self._lock``, and a direct
        widget call from a non-Qt thread would crash. The queued
        reset eventually re-enters ``_on_button_toggled(False)`` on
        the Qt thread, which calls ``stop_recording()`` — a no-op
        because we are already idle.
        """
        if self._label is not None:
            from PyQt5.QtCore import Q_ARG, QMetaObject
            from PyQt5.QtCore import Qt as QtCore
            QMetaObject.invokeMethod(
                self._label,
                "setText",
                QtCore.QueuedConnection,
                Q_ARG(str, self._file_template),
            )

        if self._button is None:
            return
        if cause == "manual":
            return

        from PyQt5.QtCore import Q_ARG, QMetaObject, Qt

        if self._button_type == "toggle":
            QMetaObject.invokeMethod(
                self._button,
                "setChecked",
                Qt.QueuedConnection,
                Q_ARG(bool, False),
            )
        else:  # push
            pass
