# SPECS — gr-file-recorder

Living technical specification. Written **before** (or alongside)
implementation — not after. This is the prompt-basis for any
code-generation pass on the block.

> The narrative/background version of this material lives in
> `docs/gr-file-recorder.md`. That document may hold prose and
> design discussion; **this** document holds the authoritative
> behaviour contract.

## 1. Data Models

### 1.1 Block parameters (GRC surface)

| # | Parameter | Type | Default | Domain |
|---|---|---|---|---|
| 1 | `file_template` | `str` | `recording_{date}_{counter}` | free text; see §2 |
| 2 | `input_type` | enum | `complex` | `complex`, `float`, `int`, `short`, `byte` |
| 3 | `vlen` | `int` | `1` | `>= 1` |
| 4 | `button_type` | enum | `toggle` | `push`, `toggle` |
| 5 | `button_name` | `str` | `""` | free text; prefixes button label |
| 6 | `show_template` | bool | `False` | show resolved filename next to button |
| 7 | `date_format` | `str` | `%Y%m%d_%H%M%S` | any `strftime` string |
| 8 | `counter_start` | `int` | `1` | any `int` |
| 9 | `counter_step` | `int` | `1` | any `int` (negative allowed) |
| 10 | `counter_style` | enum | `0-padded` | `normal`, `0-padded` |
| 11 | `record_duration` | `int` | `0` | `>= 0`; `0` = infinite seconds |
| 12 | `max_file_size` | `long` | `0` | `>= 0`; `0` = infinite bytes |

### 1.2 Type → item-size table

| `input_type` | NumPy dtype | Extension | Bytes / item (vlen=1) |
|---|---|---|---|
| `complex` | `complex64` | `fc32` | 8 |
| `float`   | `float32`   | `f32`  | 4 |
| `int`     | `int32`     | `s32`  | 4 |
| `short`   | `int16`     | `s16`  | 2 |
| `byte`    | `uint8`     | `u8`   | 1 |

`byte` is unsigned (`uint8`) to match GR's `_b` block convention.
A signed-byte interpretation is left to the consumer of the file —
the bits on disk are identical either way.

Effective item size is `bytes_per_item * vlen`.

### 1.3 Internal state (single instance)

```python
@dataclass
class _State:
    recording: bool        = False
    file:      BinaryIO | None = None
    filename:  str | None  = None
    bytes_written: int     = 0
    start_time: float | None = None   # time.monotonic()
    counter:   int         # initialised to counter_start
```

All access guarded by `self._lock: threading.Lock`.

## 2. Template Syntax

### 2.1 Single-brace built-in tokens

| Token | Replacement | Evaluated at |
|---|---|---|
| `{date}` | `datetime.now().strftime(date_format)` | recording start |
| `{counter}` | formatted per `counter_style` | recording start |
| `{type}` | extension string for `input_type` (e.g. `fc32`) | recording start |
| `{freq}` | *(reserved)* — currently replaced with `undefined` |

### 2.2 Double-brace flowgraph-variable tokens

`{{name}}` → `str(getattr(var_source, 'name', 'undefined'))`.

- `var_source` is set by the GRC make template via the public
  `set_top_block(top_block)` method, immediately after the block
  is constructed. There is no implicit lookup — the block makes no
  attempt to find its parent flowgraph through GR internals.
- If `set_top_block` was never called (e.g. headless tests), every
  `{{var}}` token resolves to the literal string `"undefined"`.
- **No exception is raised for missing variables.** Ever.

### 2.3 Counter formatting

- `normal`   → `str(counter)`           (e.g. `1`, `2`, …, `999`, `1000`)
- `0-padded` → `f"{counter:03d}"`        (e.g. `001`, `002`, …, `999`, `1000`)
  — three digits minimum; values ≥ 1000 naturally spill beyond 3 chars.

### 2.4 Resolution algorithm

The implementation lives in `python/file_recorder/file_recorder_sink.py`
as the module-level pure function `_resolve_template`. The
substitution is a **single pass** — every `{{var}}` and built-in
`{date}` / `{counter}` / `{freq}` token is matched by one alternation
regex, so a value pulled in from a `{{var}}` that happens to contain
a literal `{date}` is *not* subsequently expanded. Pseudocode:

```python
_TOKEN_RE = re.compile(r"\{\{(\w+)\}\}|\{(date|counter|freq|type)\}")

def _resolve_template(template, *, counter, counter_style,
                      date_format, var_source, now=None,
                      type_ext="") -> str:
    resolved_now = now or datetime.now()

    def replace(m):
        var, builtin = m.group(1), m.group(2)
        if var is not None:
            if var_source is None:
                return "undefined"
            return str(getattr(var_source, var, "undefined"))
        if builtin == "date":
            return resolved_now.strftime(date_format)
        if builtin == "counter":
            return _format_counter(counter, counter_style)
        if builtin == "type":
            return type_ext
        return "undefined"   # builtin == "freq" — reserved

    return _TOKEN_RE.sub(replace, template)
```

The `{type}` token resolves to the extension string (e.g. `fc32`)
so the user controls where — and whether — it appears by including
`{type}` or `.{type}` in the template. There is no automatic suffix.
Unknown single-brace tokens are **left as-is** (literal `{foo}` in
the filename) — a deliberate fail-visible choice.

Keeping `_resolve_template` as a free function makes it directly
unit-testable without constructing a full `gr.sync_block`.

## 3. State Machine

States: `IDLE`, `RECORDING`.

```
          ┌──────────────── flowgraph start ────────────────┐
          ▼                                                 │
       ┌─────┐  button_press / button_toggle_on          ┌──┴────────┐
       │ IDLE│ ─────────────────────────────────────────▶│ RECORDING │
       │     │                                            │           │
       │     │◀──────────── button_release ──────────────│           │
       │     │◀──────────── button_toggle_off ───────────│           │
       │     │◀──────────── duration_expired ────────────│           │
       │     │◀──────────── size_limit_reached ──────────│           │
       │     │◀──────────── flowgraph_stop ──────────────│           │
       └─────┘                                            └───────────┘
```

### 3.1 Transition: IDLE → RECORDING

Preconditions: none beyond "flowgraph is running".

Actions (all under `self._lock`):

1. Resolve filename via §2.4.
2. `file = open(filename, "wb")`. On `OSError`: log, stay in IDLE,
   revert the button to inactive state (queued to Qt thread).
3. `bytes_written = 0`.
4. `start_time = time.monotonic()`.
5. `recording = True`.
6. Emit `counter_for_this_cycle = counter`; `counter += counter_step`.

### 3.2 Transition: RECORDING → IDLE

Triggers:

| Trigger | Source |
|---|---|
| `button_release` | Qt thread (push mode) |
| `button_toggle_off` | Qt thread (toggle mode) |
| `duration_expired` | scheduler thread, evaluated per `work()` call |
| `size_limit_reached` | scheduler thread, evaluated per `work()` call |
| `flowgraph_stop` | `stop()` override |

Actions (all under `self._lock`):

1. `recording = False`.
2. `file.flush(); file.close(); file = None`.
3. If triggered from scheduler thread, post a queued signal to the
   Qt thread to reset the button visual to inactive
   (push: already up; toggle: un-check).
4. `start_time = None`.

The counter is **not** reset — see FR-03.

### 3.3 Stop-condition evaluation order inside `work()`

```python
with self._lock:
    if not self.recording:
        return len(in0)             # consume-and-discard
    n = len(in0)
    # 1. duration
    if record_duration > 0 and (monotonic() - start_time) >= record_duration:
        self._stop_locked(cause="duration")
        return n
    # 2. size — compute prospective write size first
    write_bytes = n * item_size
    if max_file_size > 0 and bytes_written + write_bytes >= max_file_size:
        # write up to the cap, then stop
        allowed = max(0, max_file_size - bytes_written)
        n_allowed = allowed // item_size
        file.write(in0[:n_allowed].tobytes())
        bytes_written += n_allowed * item_size
        self._stop_locked(cause="size")
        return n
    # 3. normal path
    file.write(in0.tobytes())
    bytes_written += write_bytes
    return n
```

(Exact code will differ; the **ordering and effect** are contractual.)

## 4. API Signatures

### 4.1 Python block class

```python
# python/file_recorder/file_recorder_sink.py

class file_recorder_sink(gr.sync_block):
    """GNU Radio QT GUI sink that records to disk on demand."""

    def __init__(
        self,
        file_template: str = "recording_{date}_{counter}",
        input_type: str = "complex",
        vlen: int = 1,
        button_type: str = "toggle",       # "push" | "toggle"
        date_format: str = "%Y%m%d_%H%M%S",
        counter_start: int = 1,
        counter_step: int = 1,
        counter_style: str = "0-padded",   # "normal" | "0-padded"
        record_duration: int = 0,          # seconds; 0 = infinite
        max_file_size: int = 0,            # bytes;   0 = infinite
        button_name: str = "",             # prefix for button text
        show_template: bool = False,       # show filename next to button
    ) -> None: ...

    # gr.sync_block overrides
    def work(self, input_items, output_items) -> int: ...
    def stop(self) -> bool: ...             # closes file if still open

    # programmatic control surface
    def start_recording(self) -> None: ...
    def stop_recording(self) -> None: ...
    def set_top_block(self, top_block: object | None) -> None: ...

    # read-only state (thread-safe properties)
    @property
    def is_recording(self)      -> bool:        ...
    @property
    def current_filename(self)  -> str | None:  ...
    @property
    def bytes_written(self)     -> int:         ...
    @property
    def counter(self)           -> int:         ...

    # GUI integration — called by the GRC make template
    def qwidget(self):  ...                 # QWidget container (button + label)
    def button_widget: ...                  # inner QPushButton
    def dock_area(self): ...                # Qt.TopToolBarArea
```

The button widget is constructed lazily on first `qwidget()` call,
so a headless construction (tests, batch scripts) never imports
PyQt5 and never requires a `QApplication`.

### 4.2 Module-level helpers (importable, unit-testable)

```python
INPUT_DTYPES:     dict[str, np.dtype]   # type label → dtype
INPUT_EXTENSIONS: dict[str, str]        # type label → extension
BUTTON_TYPES   = ("push", "toggle")
BUTTON_STYLES  = ("top",  "bottom")
COUNTER_STYLES = ("normal", "0-padded")

def _format_counter(value: int, style: str) -> str: ...
def _resolve_template(
    template: str,
    *,
    counter: int,
    counter_style: str,
    date_format: str,
    var_source: object | None,
    now: datetime | None = None,
) -> str: ...
```

### 4.3 Instance-private helpers

`self._lock` rules:

| Helper | Caller must hold lock |
|---|---|
| `_start_recording_locked` | yes |
| `_stop_recording_locked`  | yes |
| `_on_stopped`             | yes (called from inside `_stop_recording_locked`) |
| `_make_widget`            | no (Qt-thread only, never inside `_lock`) |
| `_on_button_toggled`      | no (Qt slot, calls `start/stop_recording` which take the lock) |
| `_on_button_pressed`      | no (Qt slot) |
| `_on_button_released`     | no (Qt slot) |

```python
def _start_recording_locked(self) -> None: ...
def _stop_recording_locked(self, *, cause: str) -> None: ...
def _on_stopped(self, *, cause: str) -> None:
    # cause ∈ {"manual", "duration", "size", "flowgraph_stop", "open_failed"}
    # Manual cause is a no-op (caller already drove the button).
    # Other causes queue setChecked(False) onto the Qt thread via
    # QMetaObject.invokeMethod(..., Qt.QueuedConnection).
```

### 4.4 GRC block YAML surface

`grc/file_recorder_sink.block.yml` exposes every parameter
from §1.1, with `dtype`, `default`, and for enums an explicit
`options` list. Category: **`[File Recorder]`**. The block has one input
port (type derived from `input_type`, `vlen` from parameter) and no
output ports.

## 5. Functional Requirements (authoritative IDs)

FR-01 … FR-12 as written in `docs/gr-file-recorder.md` §"Functional
Requirements" are the contract. They are referenced by number from
tests and commit messages. If an FR is ever revised:

1. Update `docs/gr-file-recorder.md`.
2. Mirror the change here if the mathematical/behavioural contract
   shifts.
3. Record the revision in `CONTEXT_WINDOW.md` → *Revision History*.

## 6. Test Matrix

The shipped suite (`uv run pytest`) is split between fast unit
cases that do not touch the scheduler and end-to-end cases that
drive the block through `gr.top_block`.

| Test file | Surface |
|---|---|
| `tests/test_unit_template.py`   | `_format_counter`, `_resolve_template`, constants |
| `tests/test_unit_block.py`      | constructor validation, lifecycle without scheduler |
| `tests/test_unit_work.py`       | `work()` directly: writes, size cap, **duration cap**, `stop()` |
| `tests/test_integration_record.py`   | byte-for-byte fidelity through `gr.top_block` for every input_type at vlen=1, plus complex at vlen=4 |
| `tests/test_integration_caps.py`     | size cap end-to-end (vlen=1 and vlen=4 alignment) |
| `tests/test_integration_topblock.py` | `set_top_block` + `{{var}}` resolution end-to-end |
| `tests/test_qt_button.py`            | `qwidget()`, `button_widget`, `button_name`, `show_template`, push/toggle, queued reset (under `pytest-qt`) |

Coverage axes:

| Axis | Values exercised |
|---|---|
| `input_type` | all 5 |
| `vlen` | `1`, `4` |
| `button_type` | `push`, `toggle` |
| `button_name` | default, custom prefix |
| `show_template` | enabled, disabled |
| `record_duration` | `0`, triggered case (via direct `work()` call) |
| `max_file_size` | `0`, aligned cap, mis-aligned cap |
| Template | static, `{date}`, `{counter}`, `{type}`, `{{var}}`, combined, missing var, unknown token |

Auto-stop assertions cover **byte count after stop** and, in
toggle mode, **button check-state after the queued reset has been
delivered** (`qtbot.waitUntil`). Duration cap is exercised at the
`work()` level so the suite stays deterministic; an end-to-end
duration test would require a throttled source and real wall-clock
waits without adding behavioural coverage.
