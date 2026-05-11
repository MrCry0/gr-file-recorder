# ARCHITECTURE — gr-file-recorder

This document describes **how the code is organised** and the patterns
any change must follow. When a change in this repo conflicts with this
document, either the change is wrong or this document must be updated
first — never both silently.

## Folder Structure

```
gr-file-recorder/
├── README.md                             # entry point, links to the other docs
├── OVERVIEW.md                           # vision, core loop, DoD
├── ARCHITECTURE.md                       # this file
├── SPECS.md                              # living feature spec (FR-xx)
├── CONTEXT_WINDOW.md                     # revision history + resolved conflicts
├── PLAN.md                               # phased development roadmap
├── LICENSE
├── pyproject.toml                        # PEP 621 metadata + build config
│
├── grc/
│   └── file_recorder_sink.block.yml      # GRC block descriptor
│
├── debian/                               # Ubuntu 24.04 (noble) packaging
│   ├── changelog
│   ├── control
│   ├── copyright
│   ├── rules                             # dh + pybuild-plugin-pyproject
│   └── source/format                     # 3.0 (native)
│
├── python/
│   └── file_recorder/
│       ├── __init__.py                   # re-exports public block class
│       ├── bindings/
│       │   └── __init__.py               # empty — no C++ bindings
│       └── file_recorder_sink.py         # block implementation (single file)
│
├── tests/
│   ├── test_unit_*.py                    # pure-logic + work() unit tests
│   ├── test_integration_*.py             # gr.top_block end-to-end tests
│   └── test_qt_button.py                 # pytest-qt cases for the button
│
├── examples/
│   └── file_recorder_demo.grc            # example flowgraph (optional)
│
└── docs/
    └── gr-file-recorder.md               # extended narrative / background
```

**Rule:** no C++ sources. If a requirement forces C++, update this doc
and `OVERVIEW.md` → *Key Constraints* **before** adding the sources.

**Rule:** packaging is `pyproject.toml` only. No `setup.cfg`, no
`setup.py`, no `CMakeLists.txt` in this iteration — see
`CONTEXT_WINDOW.md` for the rationale and the conditions under which
CMake support might return. The `debian/` directory consumes
`pyproject.toml` via `pybuild-plugin-pyproject`; the GRC YAML is
installed system-wide through `[tool.setuptools.data-files]`, not
through CMake `install()` rules.

## Dependency Management

- **Tooling**: `uv` is the only supported package manager. Plain
  `pip` is not used in this project (commands, docs, CI). See
  `README.md` → *Install* for the canonical invocation.
- **Runtime dependencies** (declared in `pyproject.toml`
  `[project] dependencies`):
  - `gnuradio >= 3.10` — supplied by the **host** install, not by uv.
  - `PyQt5` — supplied by the host install.
  - The list in `pyproject.toml` is therefore intentionally empty;
    the host packages are picked up via a `--system-site-packages`
    venv created with `uv venv --system-site-packages`.
- **Build dependencies**: `setuptools >= 64` (declared in
  `[build-system] requires`).
- **Dev/test dependencies** (declared under
  `[project.optional-dependencies] dev`):
  `pytest`, `pytest-qt`, `numpy`.
- Lockfile: none — this is a library, not an application.
- No vendored third-party code. No network calls at runtime.

If a new runtime dependency is required, justify it in
`CONTEXT_WINDOW.md` under *Integration Notes*, add it to
`pyproject.toml`, and bump the README install notes in the same
commit series.

## Communication Patterns

The block spans two threads, so communication is deliberately narrow.

### Scheduler thread ↔ Qt event thread

- **Shared state** lives on `self`:
  - `self._recording: bool`
  - `self._file: Optional[BinaryIO]`
  - `self._bytes_written: int`
  - `self._start_time: Optional[float]`  *(monotonic)*
  - `self._counter: int`
- **Single lock**: `self._lock = threading.Lock()` guards **all** of
  the above. No per-field locks, no `RLock`, no lock-free tricks.
- **Allowed crossings** (always under the lock):
  1. Qt button callback → sets `_recording = True/False`, opens/closes
     file, resets counters.
  2. `work()` → reads `_recording`, writes bytes, updates counters,
     may trigger stop which flips `_recording = False` and
     **posts** the button state change back to the Qt thread via
     `QMetaObject.invokeMethod(..., Qt.QueuedConnection)` or an
     equivalent queued signal.
- **Never** call Qt widget methods directly from the scheduler
  thread — always queue.

### GRC ↔ block

- **Construction only.** All parameters listed in `SPECS.md` are
  passed once to `__init__`. There is no runtime parameter-change
  hook. This is intentional: GRC regenerates the flowgraph on edit.

### Flowgraph variables

- Looked up by name at **recording start** via `getattr(top_block,
  name, "undefined")`. No listener, no caching, no observer pattern.

### Events vs. interfaces — choice rationale

| Concern | Pattern | Why |
|---|---|---|
| Button → block state | Direct method call + lock | One consumer, one event source, no fan-out |
| Scheduler → button visual | Queued Qt signal/invoke | Must cross threads; Qt requires it |
| Block ↔ top_block vars | Attribute read | GNU Radio idiom; no observer needed |
| Block ↔ file | Blocking I/O in `work()` | Disk I/O on the scheduler thread is acceptable for this use case; async I/O would add complexity without measured benefit |

If disk I/O latency is ever shown to starve the scheduler, record the
benchmark in `CONTEXT_WINDOW.md` and revisit before changing the
pattern.

## Coding Standards

- **Python 3.9+** syntax features only. Type hints on public methods.
- `black` formatting, `ruff` lint (config lives in `pyproject.toml`
  when added).
- **No globals.** All state lives on the block instance.
- **No `print`.** Use `gr.logger()` or the Python `logging` module.
- **Public surface** = the block class + the GRC YAML + `qwidget()`
  (returns container with button and optional label) + `button_widget`
  (returns the inner QPushButton).
- **One file per block** under `python/file_recorder/`. If a second
  block is added, it gets its own file.

## Extension Points (Reserved)

- `{freq}` template token is reserved for a future center-frequency
  tag. Do not repurpose.
- `input_type` enum is fixed by GNU Radio's type system — do not
  extend without a corresponding change upstream.
