from assistant import calculate


def test_addition():
    assert calculate("2 + 3") == "The answer is 5."


def test_subtraction():
    assert calculate("10 - 4") == "The answer is 6."


def test_multiplication():
    assert calculate("3 * 4") == "The answer is 12."


def test_division():
    assert calculate("20 / 5") == "The answer is 4.0."

def test_division_by_zero():
    assert calculate("10 / 0") == "Error: Division by zero is not allowed."


def test_power():
    assert calculate("2 ** 3") == "The answer is 8."


def test_huge_exponent():
    assert calculate("2 ** 101") == "Sorry, I could not calculate that expression."

def test_unsupported_syntax():
    assert calculate("2 + hello") == "Sorry, I could not calculate that expression."


def test_function_call():
    assert calculate("print(hello)") == "Sorry, I could not calculate that expression."


def test_import_statement():
    assert calculate("import os") == "Sorry, I could not calculate that expression."