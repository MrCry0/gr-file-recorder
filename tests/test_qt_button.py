# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Oleksandr Suvorov <cryosay@gmail.com>

"""Qt GUI tests for the file_recorder_sink button widget.

Uses pytest-qt's ``qtbot`` fixture, which spins up a QApplication
and lets us drive the button with synthesised mouse events. The
binding is pinned to PyQt5 in pyproject.toml because GR's qtgui
module pulls in PyQt5 — only one Qt binding can live in a process.
"""

from __future__ import annotations

import numpy as np
import pytest

# Skip the whole module gracefully if PyQt5 is unavailable, even
# though the dev extras require it. Keeps the suite green on minimal
# CI runners that lack a Qt binding.
PyQt5 = pytest.importorskip("PyQt5")
from file_recorder.file_recorder_sink import file_recorder_sink  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QLabel, QPushButton, QWidget  # noqa: E402


# --------------------------------------------------------------- helpers
@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ----------------------------------------------------------- qwidget API
class TestQwidget:
    def test_returns_container_widget(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(file_template="cap", input_type="byte")
        container = blk.qwidget()
        qtbot.addWidget(container)
        assert isinstance(container, QWidget)
        assert isinstance(blk.button_widget, QPushButton)

    def test_qwidget_is_idempotent(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(file_template="cap", input_type="byte")
        c1 = blk.qwidget()
        qtbot.addWidget(c1)
        c2 = blk.qwidget()
        assert c1 is c2

    def test_dock_area_top(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(button_style="top", input_type="byte")
        qtbot.addWidget(blk.qwidget())
        assert blk.dock_area() == Qt.TopToolBarArea

    def test_dock_area_bottom(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(button_style="bottom", input_type="byte")
        qtbot.addWidget(blk.qwidget())
        assert blk.dock_area() == Qt.BottomToolBarArea

    def test_toggle_button_is_checkable(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(button_type="toggle", input_type="byte")
        button = blk.button_widget
        qtbot.addWidget(button)
        assert button.isCheckable() is True

    def test_push_button_is_not_checkable(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(button_type="push", input_type="byte")
        button = blk.button_widget
        qtbot.addWidget(button)
        assert button.isCheckable() is False

    def test_button_text_with_name_prefix(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(
            file_template="cap", input_type="byte", button_name="IQ"
        )
        button = blk.button_widget
        qtbot.addWidget(button)
        assert button.text() == "IQ Record"


# -------------------------------------------------------- toggle behaviour
class TestToggleButton:
    def _blk(self, **kw) -> file_recorder_sink:
        kw.setdefault("file_template", "cap")
        kw.setdefault("input_type", "byte")
        kw.setdefault("button_type", "toggle")
        return file_recorder_sink(**kw)

    def test_click_starts_recording(self, qtbot, tmp_cwd) -> None:
        blk = self._blk()
        button = blk.button_widget
        qtbot.addWidget(button)

        button.click()
        assert button.isChecked() is True
        assert blk.is_recording is True

    def test_second_click_stops_recording(self, qtbot, tmp_cwd) -> None:
        blk = self._blk()
        button = blk.button_widget
        qtbot.addWidget(button)

        button.click()
        button.click()
        assert button.isChecked() is False
        assert blk.is_recording is False

    def test_size_cap_resets_button(self, qtbot, tmp_cwd) -> None:
        blk = self._blk(max_file_size=4)
        button = blk.button_widget
        qtbot.addWidget(button)

        button.click()
        assert button.isChecked() is True
        assert blk.is_recording is True

        blk.work([np.arange(8, dtype=np.uint8)], [])

        qtbot.waitUntil(lambda: not button.isChecked(), timeout=500)
        assert blk.is_recording is False

    def test_manual_stop_does_not_trigger_redundant_reset(
        self, qtbot, tmp_cwd
    ) -> None:
        blk = self._blk()
        button = blk.button_widget
        qtbot.addWidget(button)

        button.click()
        button.click()
        qtbot.wait(20)
        assert button.isChecked() is False
        assert blk.is_recording is False


# -------------------------------------------------------- push behaviour
class TestPushButton:
    def test_press_then_release_records_one_cycle(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(
            file_template="push",
            input_type="byte",
            button_type="push",
        )
        button = blk.button_widget
        qtbot.addWidget(button)

        qtbot.mousePress(button, Qt.LeftButton)
        assert blk.is_recording is True

        qtbot.mouseRelease(button, Qt.LeftButton)
        assert blk.is_recording is False

    def test_size_cap_during_hold_stops_recording(
        self, qtbot, tmp_cwd
    ) -> None:
        blk = file_recorder_sink(
            file_template="push",
            input_type="byte",
            button_type="push",
            max_file_size=4,
        )
        button = blk.button_widget
        qtbot.addWidget(button)

        qtbot.mousePress(button, Qt.LeftButton)
        assert blk.is_recording is True

        blk.work([np.arange(8, dtype=np.uint8)], [])
        qtbot.wait(20)
        assert blk.is_recording is False

        qtbot.mouseRelease(button, Qt.LeftButton)
        assert blk.is_recording is False


# ---------------------------------------------------- button name + template
class TestButtonLabel:
    def test_show_template_hides_label_by_default(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(file_template="cap", input_type="byte")
        blk.qwidget()
        assert blk._label is None

    def test_show_template_creates_label(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(
            file_template="cap_{counter}", input_type="byte",
            show_template=True, counter_style="normal",
        )
        blk.qwidget()
        assert blk._label is not None
        assert isinstance(blk._label, QLabel)

    def test_label_shows_filename_on_start(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(
            file_template="cap_{counter}", input_type="byte",
            show_template=True, counter_style="normal",
        )
        button = blk.button_widget
        qtbot.addWidget(button)
        button.click()
        assert blk._label is not None
        assert blk._label.text() == "cap_1"
        blk.stop_recording()

    def test_label_returns_to_template_pattern_on_stop(self, qtbot, tmp_cwd) -> None:
        blk = file_recorder_sink(
            file_template="cap_{counter}", input_type="byte",
            show_template=True, counter_style="normal",
        )
        button = blk.button_widget
        qtbot.addWidget(button)
        assert blk._label is not None
        # Initially shows the template pattern
        assert blk._label.text() == "cap_{counter}"
        button.click()
        # During recording shows the resolved filename
        assert blk._label.text() == "cap_1"
        button.click()
        qtbot.wait(20)
        # After stop reverts to template pattern
        assert blk._label.text() == "cap_{counter}"
