"""End-to-end integration tests against ``gr.top_block``.

A finite ``vector_source_*`` is wired into ``file_recorder_sink``;
``start_recording`` is called before ``tb.run``, the source exhausts,
the scheduler tears the flowgraph down (which in turn calls our
``stop()`` override), and the resulting file's bytes are checked
against ``np.array(data, dtype).tobytes()``.

This is the only place where we trust GR's actual scheduling — all
finer-grained behaviour is exercised by the ``test_unit_work`` suite.
"""

from __future__ import annotations

import os

import numpy as np
import pytest
from file_recorder.file_recorder_sink import INPUT_DTYPES, file_recorder_sink
from gnuradio import blocks, gr

# ----------------------------------------------------------- helpers
# Map of input_type -> (vector_source factory, list-of-samples builder).
# Keeping the source factory next to the sample builder makes the
# parametrize matrix below trivial to read.
_TYPE_BUILDERS: dict[
    str,
    "tuple[type, callable[[int], list]]",
] = {
    "complex": (blocks.vector_source_c, lambda n: [complex(i, i + 1) for i in range(n)]),
    "float":   (blocks.vector_source_f, lambda n: [float(i) * 0.5 for i in range(n)]),
    "int":     (blocks.vector_source_i, lambda n: [i - n // 2 for i in range(n)]),
    "short":   (blocks.vector_source_s, lambda n: [(i * 11) % 256 - 128 for i in range(n)]),
    "byte":    (blocks.vector_source_b, lambda n: [(i * 7) % 256 for i in range(n)]),
}


@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    """Run each test in its own cwd so resolved filenames stay scoped."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ----------------------------------------------- per-type byte fidelity
@pytest.mark.parametrize("input_type", sorted(_TYPE_BUILDERS))
def test_records_full_buffer_byte_for_byte(
    input_type: str, tmp_cwd
) -> None:
    src_factory, build = _TYPE_BUILDERS[input_type]
    data = build(64)

    src = src_factory(data, False)  # repeat=False
    sink = file_recorder_sink(
        file_template=f"cap_{input_type}",
        input_type=input_type,
    )
    sink.start_recording()

    tb = gr.top_block()
    tb.connect(src, sink)
    tb.run()

    # Source exhausted -> scheduler called sink.stop() -> file closed.
    assert sink.is_recording is False
    assert sink.current_filename is not None

    expected = np.array(data, dtype=INPUT_DTYPES[input_type]).tobytes()
    with open(sink.current_filename, "rb") as fh:
        assert fh.read() == expected
    assert sink.bytes_written == len(expected)


# ------------------------------------------------ vector input (vlen > 1)
def test_records_complex_vlen_4(tmp_cwd) -> None:
    vlen = 4
    n_items = 16
    flat = [complex(i, -i) for i in range(n_items * vlen)]

    src = blocks.vector_source_c(flat, False, vlen)
    sink = file_recorder_sink(
        file_template="vec_complex",
        input_type="complex",
        vlen=vlen,
    )
    sink.start_recording()

    tb = gr.top_block()
    tb.connect(src, sink)
    tb.run()

    expected = np.array(flat, dtype=np.complex64).tobytes()
    with open(sink.current_filename, "rb") as fh:
        assert fh.read() == expected
    assert sink.bytes_written == len(expected)


# ------------------------------------------ idle = consume-and-discard
def test_idle_block_does_not_create_file(tmp_cwd) -> None:
    """FR-11: while not recording, the sink consumes-and-discards.

    No file should be created if ``start_recording`` is never called.
    """
    data = [complex(0, 0)] * 64
    src = blocks.vector_source_c(data, False)
    sink = file_recorder_sink(
        file_template="never",
        input_type="complex",
    )
    # NOTE: deliberately NOT calling start_recording.

    tb = gr.top_block()
    tb.connect(src, sink)
    tb.run()

    assert sink.is_recording is False
    assert sink.current_filename is None
    assert sink.bytes_written == 0
    # No artefacts in the per-test cwd
    assert list(os.listdir(tmp_cwd)) == []
