# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Oleksandr Suvorov <cryosay@gmail.com>

"""Unit tests for ``file_recorder_sink.work()``.

These exercise the scheduler-facing behaviour by calling ``work``
directly with synthesised numpy buffers. That keeps the duration /
size cap tests deterministic and fast — no real wall-clock waits,
no GR scheduler. End-to-end behaviour against ``gr.top_block`` is
covered separately by the integration suite.
"""

from __future__ import annotations

import os

import numpy as np
import pytest
from file_recorder.file_recorder_sink import file_recorder_sink


@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ----------------------------------------------------- normal write path
class TestWorkWritesAllItems:
    def test_writes_all_bytes_when_no_caps(self, tmp_cwd) -> None:
        blk = file_recorder_sink(file_template="cap", input_type="byte")
        blk.start_recording()
        try:
            arr = np.arange(32, dtype=np.int8)
            consumed = blk.work([arr], [])
            assert consumed == 32
            assert blk.bytes_written == 32
            assert blk.is_recording is True
        finally:
            blk.stop_recording()

        with open(blk.current_filename, "rb") as fh:
            assert fh.read() == arr.tobytes()

    def test_consumes_input_when_idle(self, tmp_cwd) -> None:
        # FR-11: never stall the upstream pipeline. Even with no file
        # open, work() must report all items consumed.
        blk = file_recorder_sink(file_template="cap", input_type="byte")
        arr = np.arange(16, dtype=np.int8)
        assert blk.work([arr], []) == 16
        assert blk.bytes_written == 0
        assert blk.is_recording is False


# ---------------------------------------------------------- size cap path
class TestSizeCap:
    def test_truncates_to_cap_and_stops(self, tmp_cwd) -> None:
        blk = file_recorder_sink(
            file_template="cap",
            input_type="byte",
            max_file_size=10,
        )
        blk.start_recording()
        arr = np.arange(20, dtype=np.int8)  # 20 bytes; cap is 10

        consumed = blk.work([arr], [])

        assert consumed == 20            # full consumption (FR-11)
        assert blk.is_recording is False  # auto-stopped on size
        assert blk.bytes_written == 10    # exactly the cap
        with open(blk.current_filename, "rb") as fh:
            assert fh.read() == arr[:10].tobytes()

    def test_cap_respects_item_size_when_vlen_gt_one(self, tmp_cwd) -> None:
        # vlen=4 short = 8 bytes per item. Cap of 10 must not split an
        # item — only the first item (8 bytes) should be written before
        # the auto-stop fires.
        blk = file_recorder_sink(
            file_template="cap",
            input_type="short",
            vlen=4,
            max_file_size=10,
        )
        blk.start_recording()
        arr = np.arange(3 * 4, dtype=np.int16).reshape(3, 4)  # 3 items, 24 bytes
        blk.work([arr], [])

        assert blk.is_recording is False
        assert blk.bytes_written == 8     # one full item, not 10
        with open(blk.current_filename, "rb") as fh:
            assert fh.read() == arr[:1].tobytes()

    def test_cap_below_one_item_writes_nothing(self, tmp_cwd) -> None:
        # vlen=1 complex = 8 bytes per item, cap = 4. No item fits.
        blk = file_recorder_sink(
            file_template="cap",
            input_type="complex",
            max_file_size=4,
        )
        blk.start_recording()
        arr = np.arange(2, dtype=np.complex64)
        blk.work([arr], [])

        assert blk.is_recording is False
        assert blk.bytes_written == 0
        with open(blk.current_filename, "rb") as fh:
            assert fh.read() == b""


# ------------------------------------------------------ duration cap path
class TestDurationCap:
    def test_duration_trigger_stops_without_writing(self, tmp_cwd) -> None:
        # Pretend the recording started "long enough ago" to trigger
        # the cap on the next work() call. We tweak _start_time
        # directly because mocking time.monotonic in a multi-threaded
        # block invites flakes.
        blk = file_recorder_sink(
            file_template="dur",
            input_type="byte",
            record_duration=1,
        )
        blk.start_recording()
        blk._start_time -= 2.0  # 2 seconds ago > 1 second cap

        arr = np.arange(5, dtype=np.int8)
        consumed = blk.work([arr], [])

        assert consumed == 5             # full consumption
        assert blk.is_recording is False  # auto-stopped on duration
        # The work() call hit the duration check first and returned
        # without writing anything from this batch.
        assert blk.bytes_written == 0

    def test_duration_zero_means_unlimited(self, tmp_cwd) -> None:
        blk = file_recorder_sink(
            file_template="nocap",
            input_type="byte",
            record_duration=0,
        )
        blk.start_recording()
        # Even with a wildly-old start_time, duration 0 must not stop.
        blk._start_time -= 10_000.0

        arr = np.arange(8, dtype=np.int8)
        blk.work([arr], [])
        try:
            assert blk.is_recording is True
            assert blk.bytes_written == 8
        finally:
            blk.stop_recording()


# ---------------------------------------------------------- stop() override
class TestStopOverride:
    def test_stop_closes_open_file(self, tmp_cwd) -> None:
        blk = file_recorder_sink(file_template="auto", input_type="byte")
        blk.start_recording()
        assert blk.is_recording is True

        ret = blk.stop()                 # GR scheduler tear-down

        assert ret is True
        assert blk.is_recording is False
        # File should exist and be closed; we can re-open it for read.
        assert os.path.exists(blk.current_filename)

    def test_stop_when_idle_is_safe(self, tmp_cwd) -> None:
        blk = file_recorder_sink(file_template="never", input_type="byte")
        # Never started — stop() must still be safe and return True.
        assert blk.stop() is True
        assert blk.is_recording is False
