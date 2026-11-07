from assistant import is_time_question


def test_what_time_is_it():
    assert is_time_question("What time is it?") is True


def test_current_time():
    assert is_time_question("What is the current time?") is True


def test_current_date():
    assert is_time_question("What is the current date?") is True


def test_what_is_the_date():
    assert is_time_question("What is the date today?") is True


def test_hinglish_time_question():
    assert is_time_question("Abhi time kya hai?") is True


def test_hinglish_date_question():
    assert is_time_question("Aaj ki tareekh kya hai?") is True


def test_ordinary_sentence_with_time():
    assert is_time_question("I have time to study") is False


def test_unrelated_question():
    assert is_time_question("How are you doing?") is False


def test_empty_string():
    assert is_time_question("") is False


def test_unrelated_date_statement():
    assert is_time_question("Today I went shopping") is False