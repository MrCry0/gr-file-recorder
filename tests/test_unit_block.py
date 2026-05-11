# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Oleksandr Suvorov <cryosay@gmail.com>

"""Unit tests that touch the block class directly but do not run a flowgraph.

Constructor validation and the start/stop public API are exercised
without going through the GR scheduler. Integration with the
scheduler (work() being called for real, end-to-end byte counting,
auto-stop wall-clock behaviour) is covered in test_integration_*.py.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from file_recorder.file_recorder_sink import file_recorder_sink


# -------------------------------------------------------- input validation
class TestConstructorValidation:
    def test_default_construction_succeeds(self) -> None:
        blk = file_recorder_sink()
        assert blk.is_recording is False
        assert blk.current_filename is None
        assert blk.bytes_written == 0
        assert blk.counter == 1

    @pytest.mark.parametrize("bad", ["double", "uint8", "", "complex32"])
    def test_unknown_input_type_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError, match="input_type"):
            file_recorder_sink(input_type=bad)

    @pytest.mark.parametrize("bad", ["click", "", "TOGGLE"])
    def test_unknown_button_type_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError, match="button_type"):
            file_recorder_sink(button_type=bad)

    @pytest.mark.parametrize("bad", ["middle", "left", ""])
    def test_unknown_button_style_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError, match="button_style"):
            file_recorder_sink(button_style=bad)

    @pytest.mark.parametrize("bad", ["dec", "padded", ""])
    def test_unknown_counter_style_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError, match="counter_style"):
            file_recorder_sink(counter_style=bad)

    @pytest.mark.parametrize("bad", [0, -1, -42])
    def test_vlen_must_be_positive(self, bad: int) -> None:
        with pytest.raises(ValueError, match="vlen"):
            file_recorder_sink(vlen=bad)

    def test_negative_record_duration_rejected(self) -> None:
        with pytest.raises(ValueError, match="record_duration"):
            file_recorder_sink(record_duration=-1)

    def test_negative_max_file_size_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_file_size"):
            file_recorder_sink(max_file_size=-1)

    def test_all_input_types_construct(self) -> None:
        for label in ("complex", "float", "int", "short", "byte"):
            file_recorder_sink(input_type=label)


# ----------------------------------------------------------- lifecycle API
class TestLifecycle:
    """Exercise start/stop directly. The block's work() is not invoked."""

    @pytest.fixture
    def blk_in(self, tmp_path, monkeypatch):
        """Block constructed in a temp cwd so resolved filenames are local."""
        monkeypatch.chdir(tmp_path)
        return file_recorder_sink(file_template="cap_{counter}")

    def test_initial_state_is_idle(self, blk_in) -> None:
        assert blk_in.is_recording is False
        assert blk_in.current_filename is None
        assert blk_in.bytes_written == 0

    def test_start_creates_file_and_advances_counter(self, blk_in, tmp_path) -> None:
        blk_in.start_recording()
        try:
            assert blk_in.is_recording is True
            # counter advances on start (FR-03), so cycle 1 used
            # counter=1 and the field now reads 2.
            assert blk_in.counter == 2
            assert blk_in.current_filename == "cap_001"
            assert (tmp_path / "cap_001").exists()
        finally:
            blk_in.stop_recording()

    def test_stop_closes_file_and_preserves_filename(self, blk_in) -> None:
        blk_in.start_recording()
        name = blk_in.current_filename
        blk_in.stop_recording()
        assert blk_in.is_recording is False
        # filename is retained so the operator can see what was just captured
        assert blk_in.current_filename == name

    def test_start_when_already_recording_is_noop(self, blk_in) -> None:
        blk_in.start_recording()
        try:
            counter_after_first_start = blk_in.counter
            file_after_first_start = blk_in.current_filename
            blk_in.start_recording()  # second call should not advance anything
            assert blk_in.counter == counter_after_first_start
            assert blk_in.current_filename == file_after_first_start
        finally:
            blk_in.stop_recording()

    def test_stop_when_idle_is_noop(self, blk_in) -> None:
        blk_in.stop_recording()
        assert blk_in.is_recording is False

    def test_counter_persists_across_cycles(self, blk_in) -> None:
        # FR-03: the counter is not reset between cycles within one
        # flowgraph run.
        for expected in (1, 2, 3):
            blk_in.start_recording()
            assert blk_in.current_filename == f"cap_{expected:03d}"
            blk_in.stop_recording()

    def test_counter_step_is_applied(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        blk = file_recorder_sink(
            file_template="cap_{counter}",
            counter_start=10,
            counter_step=5,
            counter_style="normal",
        )
        for expected in (10, 15, 20):
            blk.start_recording()
            assert blk.current_filename == f"cap_{expected}"
            blk.stop_recording()

    def test_auto_creates_missing_parent_directory(self, monkeypatch, tmp_path) -> None:
        monkeypatch.chdir(tmp_path)
        blk = file_recorder_sink(
            file_template="auto_dir/cap_{counter}",
            input_type="byte",
            counter_style="normal",
        )
        assert not os.path.isdir("auto_dir")
        assert not os.path.isfile("auto_dir/cap_1")
        blk.start_recording()
        assert blk.is_recording is True
        assert os.path.isdir("auto_dir")
        assert os.path.isfile("auto_dir/cap_1")
        blk.stop_recording()

    def test_deep_nested_path_creates_all_intermediate_dirs(self, monkeypatch, tmp_path) -> None:
        monkeypatch.chdir(tmp_path)
        blk = file_recorder_sink(
            file_template="a/b/c/deep_cap",
            input_type="byte",
        )
        assert not os.path.isdir("a/b/c")
        blk.start_recording()
        assert blk.is_recording is True
        assert os.path.isfile("a/b/c/deep_cap")
        blk.stop_recording()

    def test_tilde_in_template_expands_to_home(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        blk = file_recorder_sink(
            file_template="~/test_tilde_expand/cap_{counter}",
            input_type="byte",
            counter_style="normal",
        )
        home = os.path.expanduser("~")
        expected_dir = os.path.join(home, "test_tilde_expand")
        assert not os.path.isdir(expected_dir)
        blk.start_recording()
        assert blk.is_recording is True
        assert os.path.isdir(expected_dir)
        assert os.path.isfile(os.path.join(expected_dir, "cap_1"))
        blk.stop_recording()


# ------------------------------------------------------------ var lookup API
class TestSetTopBlock:
    def test_resolve_uses_provided_var_source(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        blk = file_recorder_sink(
            file_template="cap_{{samp_rate}}_{counter}",
            counter_style="normal",
        )
        blk.set_top_block(SimpleNamespace(samp_rate=2_500_000))
        blk.start_recording()
        try:
            assert blk.current_filename == "cap_2500000_1"
        finally:
            blk.stop_recording()

    def test_resolve_undefined_when_top_block_is_none(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        blk = file_recorder_sink(
            file_template="cap_{{samp_rate}}",
            counter_style="normal",
        )
        # Default: never called set_top_block -> source is None
        blk.start_recording()
        try:
            assert blk.current_filename == "cap_undefined"
        finally:
            blk.stop_recording()

    def test_resolve_undefined_for_missing_attribute(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        blk = file_recorder_sink(
            file_template="cap_{{nope}}",
            counter_style="normal",
        )
        blk.set_top_block(SimpleNamespace(samp_rate=1))
        blk.start_recording()
        try:
            assert blk.current_filename == "cap_undefined"
        finally:
            blk.stop_recording()
