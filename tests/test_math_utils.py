from src.math_utils import add
import pytest


def test_add_positive():
    assert add(2, 3) == 5


def test_add_negative_and_positive():
    assert add(-1, 1) == 0


def test_add_floats():
    assert add(0.1, 0.2) == pytest.approx(0.3)
