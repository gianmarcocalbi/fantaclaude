from fantaclaude.values import is_number


def test_is_number_refuses_bools_and_the_non_finite_floats():
    assert all(is_number(v) for v in (0, 1, -3, 0.5, -2.5, 10 ** 400))     # a huge int is finite, and must not overflow
    assert not any(is_number(v) for v in (True, False, None, "3", [1], {}, (),
                                          float("nan"), float("inf"), float("-inf")))
