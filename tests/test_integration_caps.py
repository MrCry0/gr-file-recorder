"""Integration tests for the size and duration caps under ``gr.top_block``.

Size cap is exercised end-to-end: a source larger than the cap is
fed in, and we assert that the resulting file size is exactly the
cap and that the recorder is no longer recording when the flowgraph
finishes.

Duration cap is left to the unit-level work() suite — exercising it
end-to-end requires a throttled source and real wall-clock waits,
which makes the suite slow and flaky for no extra coverage.
"""

from __future__ import annotations

import numpy as np
import pytest
from file_recorder.file_recorder_sink import file_recorder_sink
from gnuradio import blocks, gr


@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_size_cap_truncates_file_to_exact_byte_count(tmp_cwd) -> None:
    cap = 32  # bytes
    data = list(range(256))  # 256 distinct uint8 values, much larger than cap

    src = blocks.vector_source_b(data, False)
    sink = file_recorder_sink(
        file_template="size_cap",
        input_type="byte",
        max_file_size=cap,
    )
    sink.start_recording()

    tb = gr.top_block()
    tb.connect(src, sink)
    tb.run()

    assert sink.is_recording is False
    assert sink.bytes_written == cap

    with open(sink.current_filename, "rb") as fh:
        written = fh.read()
    assert len(written) == cap
    # The cap kicks in at the *first* work() call that crosses the
    # threshold, but the head of the source is what landed on disk.
    expected_prefix = np.array(data[:cap], dtype=np.uint8).tobytes()
    assert written == expected_prefix


@pytest.mark.parametrize("vlen, item_bytes", [(1, 8), (4, 32)])
def test_size_cap_with_complex_respects_item_boundaries(
    tmp_cwd, vlen: int, item_bytes: int
) -> None:
    # Cap not aligned to item size: must round DOWN to the nearest
    # whole item so an IQ sample (or vector) is never split.
    cap = item_bytes * 3 + 1     # e.g. 25 for vlen=1, 97 for vlen=4
    expected_bytes = item_bytes * 3
    n_items = 16
    data = [complex(i, -i) for i in range(n_items * vlen)]

    src = blocks.vector_source_c(data, False, vlen)
    sink = file_recorder_sink(
        file_template="vec_cap",
        input_type="complex",
        vlen=vlen,
        max_file_size=cap,
    )
    sink.start_recording()

    tb = gr.top_block()
    tb.connect(src, sink)
    tb.run()

    assert sink.bytes_written == expected_bytes
    with open(sink.current_filename, "rb") as fh:
        assert len(fh.read()) == expected_bytes
