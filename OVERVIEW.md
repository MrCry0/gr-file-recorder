# OVERVIEW — gr-file-recorder

## Project Pitch

`gr-file-recorder` is a GNU Radio Out-of-Tree (OOT) module that provides a
**QT GUI sink block** capable of recording a sample stream to disk with
flexible, template-driven file naming and GUI-driven start/stop control.

It is a drop-in replacement for `blocks.file_sink` in flowgraphs where an
operator — not a script — decides when to record. All file-lifecycle
concerns (filename resolution, open/close, byte counting, duration
tracking) are handled inside the block. No external Python glue, no
message passing, no flowgraph regeneration required.

## Core Loop

```
flowgraph starts
  → block initialises counter, installs QT button in GUI
  → samples flow in, block consumes-and-discards while inactive
operator presses/toggles button
  → block resolves filename template (date, counter, type, flowgraph vars)
  → opens file, sets `recording = True`, records start time
  → work() writes samples, updates bytes_written on every call
  → stop triggers: operator release/toggle, record_duration, max_file_size
  → block flushes, closes file, sets `recording = False`
  → counter advances; ready for next cycle
flowgraph stops
  → any open file is flushed and closed cleanly
```

## Target Platform

| Layer | Choice |
|---|---|
| Runtime | GNU Radio **3.10+** (Python block API, QT GUI) |
| Language | **Pure Python** — no C++ sources |
| GUI | PyQt5 via GNU Radio's `qtgui` integration |
| Install | `uv pip install -e .` into a `--system-site-packages` venv |
| OS | Linux primary; macOS best-effort (same Python API) |

## Key Constraints

- **Pure-Python OOT.** No `lib/` or `include/` tree — avoids the C++
  toolchain entirely and keeps the module editable without rebuilds.
- **Thread-safe.** `work()` runs in the scheduler thread; button
  callbacks run in the Qt event thread. All shared state
  (`recording`, file handle, `bytes_written`, `start_time`) must sit
  behind a lock.
- **Never stall the pipeline.** When inactive, the block must still
  consume its input — it is a sink, not a gate.
- **Self-contained.** No reliance on `file_sink.open/close`,
  `file_descriptor_sink`, or post-processing of GRC-generated Python.
- **Overwrite semantics.** If the resolved filename exists, it is
  overwritten. No implicit uniqueness beyond the counter/date tokens.
- **Unknown flowgraph variables resolve to the literal `undefined`**
  rather than raising — records must never be lost to a typo.

## Definition of Done

The project is "done" for an MVP release when **all** of the following
hold:

1. All functional requirements **FR-01 … FR-12** (see `SPECS.md`) are
   implemented and covered by tests.
2. The block appears in GRC under the **File Recorder** category after
   a system install (`apt install ./gr-file-recorder_*.deb` or
   `sudo uv pip install --system .`), with no manual `.py` patching
   and no `GRC_BLOCKS_PATH` export.
3. Both `push` and `toggle` button modes work on a live flowgraph with
   a file-sink replacement, validated against all five sample types
   (`complex`, `float`, `int`, `short`, `byte`) and `vlen` ≥ 1.
4. Auto-stop triggers (`record_duration`, `max_file_size`) stop
   recording within one `work()` call of the trigger condition, and
   visibly reset the button to its inactive state.
5. No pipeline stall when recording is inactive — verified by a
   long-running flowgraph whose upstream sample rate is maintained.
6. All five required docs (`README`, `OVERVIEW`, `ARCHITECTURE`,
   `SPECS`, `CONTEXT_WINDOW`) exist at the project root and accurately
   describe the shipped behaviour.
7. `uv pip install -e .` succeeds from a clean checkout on a stock
   GNU Radio 3.10 install (with a `--system-site-packages` venv),
   and the example flowgraph in `examples/` runs end-to-end.
