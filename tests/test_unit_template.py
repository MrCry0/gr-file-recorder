# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Oleksandr Suvorov <cryosay@gmail.com>

"""Unit tests for the pure-logic helpers in file_recorder_sink.

These tests do not construct a gr.sync_block — they exercise
_format_counter, _resolve_template, and the static lookup tables.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from file_recorder.file_recorder_sink import (
    BUTTON_STYLES,
    BUTTON_TYPES,
    COUNTER_STYLES,
    INPUT_DTYPES,
    INPUT_EXTENSIONS,
    _format_counter,
    _resolve_template,
)


# ---------------------------------------------------------------- constants
class TestConstants:
    def test_input_dtype_keys_match_extension_keys(self) -> None:
        assert set(INPUT_DTYPES) == set(INPUT_EXTENSIONS)

    @pytest.mark.parametrize(
        "label, expected_itemsize, expected_ext",
        [
            ("complex", 8, "fc32"),
            ("float",   4, "f32"),
            ("int",     4, "s32"),
            ("short",   2, "s16"),
            ("byte",    1, "u8"),
        ],
    )
    def test_dtype_and_extension_match_specs(
        self, label: str, expected_itemsize: int, expected_ext: str
    ) -> None:
        assert INPUT_DTYPES[label].itemsize == expected_itemsize
        assert INPUT_EXTENSIONS[label] == expected_ext

    def test_enum_tuples_are_immutable_tuples(self) -> None:
        # Catches accidental list -> tuple regressions that would let
        # callers mutate the canonical enum sets.
        assert isinstance(BUTTON_TYPES, tuple)
        assert isinstance(BUTTON_STYLES, tuple)
        assert isinstance(COUNTER_STYLES, tuple)


# ----------------------------------------------------------- format_counter
class TestFormatCounter:
    @pytest.mark.parametrize(
        "value, style, expected",
        [
            (1,    "normal",    "1"),
            (42,   "normal",    "42"),
            (1000, "normal",    "1000"),
            (-1,   "normal",    "-1"),
            (1,    "0-padded",  "001"),
            (42,   "0-padded",  "042"),
            (999,  "0-padded",  "999"),
            (1000, "0-padded",  "1000"),     # SPECS §2.3: spills past 3 chars
            (0,    "0-padded",  "000"),
        ],
    )
    def test_known_styles(self, value: int, style: str, expected: str) -> None:
        assert _format_counter(value, style) == expected

    def test_unknown_style_raises(self) -> None:
        with pytest.raises(ValueError, match="counter_style"):
            _format_counter(1, "decimal")


# --------------------------------------------------------- resolve_template
class TestResolveTemplate:
    FROZEN = datetime(2026, 4, 27, 14, 30, 22)

    def _resolve(self, template: str, **overrides: object) -> str:
        kwargs: dict[str, object] = {
            "counter": 1,
            "counter_style": "0-padded",
            "date_format": "%Y%m%d_%H%M%S",
            "var_source": None,
            "now": self.FROZEN,
            "type_ext": "",
        }
        kwargs.update(overrides)
        return _resolve_template(template, **kwargs)  # type: ignore[arg-type]

    # --- single-brace built-ins
    def test_date_token(self) -> None:
        assert self._resolve("cap_{date}") == "cap_20260427_143022"

    def test_date_format_is_honoured(self) -> None:
        assert self._resolve("cap_{date}", date_format="%Y") == "cap_2026"

    def test_counter_token_padded(self) -> None:
        assert self._resolve("c_{counter}", counter=7) == "c_007"

    def test_counter_token_normal(self) -> None:
        assert self._resolve("c_{counter}", counter=7, counter_style="normal") == "c_7"

    def test_type_token_resolves_to_type_ext(self) -> None:
        assert self._resolve("cap.{type}", type_ext="fc32") == "cap.fc32"

    def test_type_token_defaults_to_empty_when_omitted(self) -> None:
        assert self._resolve("cap{type}") == "cap"

    def test_freq_token_is_reserved_and_resolves_undefined(self) -> None:
        assert self._resolve("f_{freq}") == "f_undefined"

    def test_unknown_single_brace_left_as_literal(self) -> None:
        # SPECS §2.4: fail-visible, not silently dropped.
        assert self._resolve("x_{unknown}_y") == "x_{unknown}_y"

    # --- double-brace flowgraph variables
    def test_double_brace_with_var_source(self) -> None:
        tb = SimpleNamespace(samp_rate=2_000_000, channel="ch1")
        out = self._resolve("cap_{{samp_rate}}_{{channel}}", var_source=tb)
        assert out == "cap_2000000_ch1"

    def test_double_brace_missing_var_resolves_undefined(self) -> None:
        tb = SimpleNamespace(samp_rate=1_000_000)
        assert self._resolve("cap_{{missing}}", var_source=tb) == "cap_undefined"

    def test_double_brace_no_var_source_resolves_undefined(self) -> None:
        assert self._resolve("cap_{{anything}}", var_source=None) == "cap_undefined"

    # --- ordering / mixing
    def test_double_brace_resolved_before_single_brace(self) -> None:
        # If a flowgraph var contains a literal "{date}", that {date}
        # must NOT be subsequently expanded.
        tb = SimpleNamespace(name="prefix_{date}")
        out = self._resolve("{{name}}_tail", var_source=tb)
        assert out == "prefix_{date}_tail"

    def test_combined_template(self) -> None:
        tb = SimpleNamespace(samp_rate=2_000_000)
        out = self._resolve(
            "iq_{{samp_rate}}_{date}_{counter}",
            counter=42,
            var_source=tb,
        )
        assert out == "iq_2000000_20260427_143022_042"

    def test_template_with_no_tokens_passes_through(self) -> None:
        assert self._resolve("plain_filename") == "plain_filename"

    # --- inplace flow variables: type / edge variants
    @pytest.mark.parametrize(
        ("template", "var_attrs", "expected"),
        [
            ("cap_{{freq}}",         {"freq": 1000},                         "cap_1000"),
            ("cap_{{gain}}",         {"gain": 0.5},                          "cap_0.5"),
            ("cap_{{flag}}",         {"flag": True},                         "cap_True"),
            ("cap_{{flag}}",         {"flag": False},                        "cap_False"),
            ("cap_{{val}}",          {"val": None},                          "cap_None"),
            ("{{prefix}}cap",        {"prefix": ""},                         "cap"),
            ("cap_{{freq}}-{{freq}}", {"freq": 1000},                        "cap_1000-1000"),
            ("/tmp/{{freq}}/cap",    {"freq": 1000},                         "/tmp/1000/cap"),
            ("cap_{{samp_rate_1}}",  {"samp_rate_1": 2_000_000},             "cap_2000000"),
            ("{{a}}_{{b}}_{{c}}",    {"a": "x", "b": "y", "c": "z"},        "x_y_z"),
        ],
    )
    def test_flow_variable_inplace_variants(
        self, template: str, var_attrs: dict[str, object], expected: str
    ) -> None:
        tb = SimpleNamespace(**var_attrs)
        out = self._resolve(template, var_source=tb)
        assert out == expected
