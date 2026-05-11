# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Oleksandr Suvorov <cryosay@gmail.com>

"""Integration tests for ``set_top_block`` + ``{{var}}`` resolution.

Confirms the wiring that the GRC make template will eventually do:
construct the block, hand it the top_block instance, then run.
"""

from __future__ import annotations

from file_recorder.file_recorder_sink import file_recorder_sink
from gnuradio import blocks, gr


class _CapturingTopBlock(gr.top_block):
    """Top block exposing flowgraph variables as attributes.

    GRC produces structurally similar code: every variable in the
    flowgraph becomes an attribute on the generated top_block class.
    """

    def __init__(self, samp_rate: int, channel: str) -> None:
        gr.top_block.__init__(self, "capturing_tb")
        self.samp_rate = samp_rate
        self.channel = channel


def test_double_brace_resolves_from_top_block(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    tb = _CapturingTopBlock(samp_rate=2_000_000, channel="ch1")
    sink = file_recorder_sink(
        file_template="iq_{{samp_rate}}_{{channel}}_{counter}",
        input_type="complex",
        counter_style="normal",
    )
    sink.set_top_block(tb)

    src = blocks.vector_source_c([0j] * 8, False)
    tb.connect(src, sink)

    sink.start_recording()
    tb.run()

    assert sink.current_filename == "iq_2000000_ch1_1"
    assert (tmp_path / "iq_2000000_ch1_1").exists()


def test_missing_var_resolves_to_undefined(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    tb = _CapturingTopBlock(samp_rate=1_000_000, channel="ch0")
    sink = file_recorder_sink(
        file_template="cap_{{nonexistent}}",
        input_type="complex",
    )
    sink.set_top_block(tb)

    src = blocks.vector_source_c([0j] * 4, False)
    tb.connect(src, sink)

    sink.start_recording()
    tb.run()

    assert sink.current_filename == "cap_undefined"
