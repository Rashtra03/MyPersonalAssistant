
import requests
import datetime
import ast
import operator

def is_time_question(text):
    q = text.lower().strip()

    keys = [
        "time", "date", "today", "day",
        "abhi time", "samay", "tareekh", "aaj"
    ]

    question_phrases = [
        "what time",
        "time kya",
        "date kya",
        "tareekh kya",
        "samay kya",
        "aaj kya",
        "aaj ki tareekh",
        "abhi time",
        "current date",
        "current time",
        "which day",
        "what day",
        "what is the date"
    ]

    return (
        any(key in q for key in keys)
        and any(phrase in q for phrase in question_phrases)
    )

# ---------------- CONFIGURATION ----------------

MODEL = "llama3.2:3b"
OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_PROMPT = """
You are a helpful personal AI assistant.

Rules:
1. Always answer in clear and simple English only.
2. Never answer in Hindi or Hinglish.
3. Explain concepts in an easy-to-understand way.
4. Be polite, friendly, and helpful.
5. If you do not know something, say so honestly.
"""

# ---------------- GREETING ----------------

def greet():
    hour = datetime.datetime.now().hour

    if hour < 12:
        greeting = "Good morning!"
    elif hour < 17:
        greeting = "Good afternoon!"
    else:
        greeting = "Good evening!"

    print("\n" + "=" * 45)
    print("       MY PERSONAL AI ASSISTANT")
    print("=" * 45)
    print(greeting)
    print("I am ready to help you.")
    print("Type 'help' to see commands.")
    print("Type 'bye' to exit.")
    print("=" * 45)


# ---------------- TIME ----------------

def get_time():
    current_time = datetime.datetime.now().strftime("%I:%M:%S %p")
    return f"The current time is {current_time}."


# ---------------- DATE ----------------

def get_date():
    current_date = datetime.datetime.now().strftime("%d %B %Y")
    return f"Today's date is {current_date}."


# ---------------- CALCULATOR ----------------

def calculate(expression):
    """
    Safely evaluates basic arithmetic expressions.
    Supports +, -, *, /, //, %, and **.
    """

    allowed_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos
    }

    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value

        if isinstance(node, ast.BinOp):
            left = evaluate(node.left)
            right = evaluate(node.right)

            op_type = type(node.op)

            if op_type not in allowed_operators:
                raise ValueError("Unsupported operator")

            if op_type == ast.Pow and abs(right) > 100:
                raise ValueError("Exponent is too large")

            return allowed_operators[op_type](left, right)

        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)

            if op_type not in allowed_operators:
                raise ValueError("Unsupported operator")

            return allowed_operators[op_type](evaluate(node.operand))

        raise ValueError("Invalid mathematical expression")

    try:
        parsed_expression = ast.parse(expression, mode="eval")
        result = evaluate(parsed_expression.body)
        return f"The answer is {result}."

    except ZeroDivisionError:
        return "Error: Division by zero is not allowed."

    except Exception:
        return "Sorry, I could not calculate that expression."


# ---------------- AI CHAT ----------------

def ask_ai(user_message):
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": user_message
                    }
                ],
                "stream": False
            },
            timeout=120
        )

        response.raise_for_status()

        data = response.json()
        answer = data["message"]["content"]

        return answer.strip()

    except requests.exceptions.ConnectionError:
        return (
            "I cannot connect to Ollama. "
            "Please make sure Ollama is running."
        )

    except requests.exceptions.Timeout:
        return (
            "The AI is taking too long to respond. "
            "Please try again."
        )

    except Exception as error:
        return f"An error occurred: {error}"


# ---------------- HELP ----------------

def show_help():
    print("\nAvailable commands:")
    print("1. time       - Show current time")
    print("2. date       - Show today's date")
    print("3. calculate  - Calculate a mathematical expression")
    print("4. help       - Show available commands")
    print("5. bye        - Exit the assistant")
    print("\nYou can also ask any general question.")


# ---------------- MAIN ASSISTANT ----------------

def run_assistant():
    greet()

    while True:
        user_input = input("\nYou: ").strip()

        if not user_input:
            continue

        command = user_input.lower()

        # Exit
        if command in ["bye", "exit", "quit", "goodbye"]:
            print("\nAssistant: Goodbye! Have a great day.")
            break

        # Help
        elif command == "help":
            show_help()

        # Time
        elif command in ["time", "what is the time", "what time is it"]:
            print("\nAssistant:", get_time())

        # Date
        elif command in ["date", "what is the date", "today's date"]:
            print("\nAssistant:", get_date())

        # Calculator
        elif command.startswith("calculate "):
            expression = user_input[10:].strip()
            print("\nAssistant:", calculate(expression))

        # General AI question
        else:
            print("\nAssistant: Thinking...")
            answer = ask_ai(user_input)
            print("\nAssistant:", answer)


# ---------------- START ----------------

if __name__ == "__main__":
    run_assistant()


