import pytest

from nova.main import safe_calculate


def test_basic_arithmetic():
    assert safe_calculate("2 + 3 * 4") == 14
    assert safe_calculate("(10 - 4) / 2") == 3


def test_unary_arithmetic():
    assert safe_calculate("-5 + +2") == -3


@pytest.mark.parametrize("expression", [
    "__import__('os').system('echo unsafe')",
    "open('/etc/passwd')",
    "x + 1",
    "2 ** 99",
])
def test_rejects_unsafe_or_excessive_expressions(expression):
    with pytest.raises((ValueError, TypeError, SyntaxError)):
        safe_calculate(expression)
