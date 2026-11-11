import pytest

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


@pytest.mark.parametrize(
    "prompt",
    [
        "today's date",
        "Today’s date?",
        "What is today's date?",
        "What's the time?",
        "What is the time right now?",
        "Can you tell me the current date?",
        "Hey Jugnu, what day is it today?",
        "Which day of the week is it?",
        "What is the date and time?",
        "aaj ki date kya hai?",
        "Aaj ki date batao",
        "Time kya hua hai?",
        "Abhi samay kya hai?",
        "Aaj kaun sa din hai?",
        "Aaj kya day hai?",
        "Aaj kitni tareekh hai?",
        "Abhi kitne baje hain?",
        "Aaj ki date aur time kya hai?",
        "  what   time   is   it?! ",
    ],
)
def test_real_time_and_date_questions_return_true(prompt):
    assert is_time_question(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    [
        "What should I study today?",
        "Aaj kya padhu?",
        "Aaj kya plan hai?",
        "Aaj ka din kaisa rahega?",
        "Abhi time nahi hai padhne ka",
        "What time does the train leave?",
        "What time is the meeting?",
        "What time complexity does merge sort have?",
        "What is the date of the exam?",
        "What day is Diwali?",
        "Which day is best for studying?",
        "Do you have time?",
        "How do I get the current time in Python?",
        "What is the current time in Tokyo?",
        "What is the current timestamp?",
        "Today's date is 11 November 2026",
        "runtime kya hai?",
        "update kya hai?",
        "kaaj kya hai?",
        "Exam ki date kya hai?",
        "Train ka time kya hai?",
        "Tareekh pe tareekh",
        "today",
        "aaj",
        "   ",
        "???",
        None,
    ],
)
def test_false_positives_and_non_time_prompts_return_false(prompt):
    assert is_time_question(prompt) is False
