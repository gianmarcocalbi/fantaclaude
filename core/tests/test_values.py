from fantaclaude.values import is_number


def test_is_number_refuses_bools_and_the_non_finite_floats():
    assert all(is_number(v) for v in (0, 1, -3, 0.5, -2.5, 10 ** 400))     # a huge int is finite, and must not overflow
    assert not any(is_number(v) for v in (True, False, None, "3", [1], {}, (),
                                          float("nan"), float("inf"), float("-inf")))


def test_json_safe_scrubs_non_finite_floats_at_any_depth():
    import json
    import math

    from fantaclaude.values import json_safe

    value = {"a": -math.inf, "b": [1.0, math.nan, (2, math.inf)], "c": {"d": 3}, "e": "x", "f": True}
    safe = json_safe(value)
    assert safe == {"a": None, "b": [1.0, None, [2, None]], "c": {"d": 3}, "e": "x", "f": True}
    json.dumps(safe, allow_nan=False)                     # what a DuckDB JSON column and a tool result both need
    assert json_safe(1.5) == 1.5 and json_safe(None) is None
