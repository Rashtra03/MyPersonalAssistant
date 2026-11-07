"""All user-facing text for JUGNU, in one place.

To add a language:
  1. Add a new dictionary to STRINGS with exactly the same keys as "en".
  2. Add its code to LANGUAGES (the Language button cycles through that list).

Keep placeholders such as {error} and {when} identical in every language.
Never name a placeholder "language" or "key": those are get_string() arguments.
Brand text (the name JUGNU and its acronym expansion) is not translated.
"""

DEFAULT_LANGUAGE = "en"
LANGUAGES = ["en", "hinglish"]

STRINGS = {
    "en": {
        "language_name": "English",
        "language_btn": "🌐  Language: {name}",
        # Sidebar and header
        "new_chat_btn": "＋  New Chat",
        "history_label": "CHAT HISTORY",
        "clear_chat_btn": "▤  Clear Current Chat",
        "voice_on": "🔊  Voice: On",
        "voice_off": "🔇  Voice: Off",
        "theme_to_light": "☼  Light Mode",
        "theme_to_dark": "☾  Dark Mode",
        "header_title": "✦  Your little genius is here!",
        # Chat area
        "send_btn": "➤  Send",
        "you_label": "You",
        "welcome_title": "Hey! I'm JUGNU",
        "welcome_prompt": "What would you like to explore today?",
        # Status line
        "status_ready": "Ready",
        "status_offline": "Ollama offline",
        "status_thinking": "Thinking…",
        "status_save_error": "Could not save history: {error}",
        # Dialogs
        "clear_dialog_title": "Clear Current Chat",
        "clear_dialog_message": "Permanently remove this chat from your history?",
        # Replies shown when something goes wrong
        "error_empty_reply": "Sorry, I got an empty response. Please try again.",
        "error_timeout": ("The reply is taking too long. Please check that Ollama is running "
                          "and the model has loaded, then try again."),
        "error_connection": ("Can't connect to Ollama. Please check that Ollama is running "
                             "and the model is installed."),
        "error_generic": "Error: {error}",
        # Answered locally, without calling the model
        "time_answer": "The current local date and time is: {when}",
        # Added to the system prompt so the model replies in this language
        "prompt_language_rule": ("Always answer in clear and simple English only. "
                                 "Never answer in Hindi or Hinglish. "),
    },
    "hinglish": {
        "language_name": "Hinglish",
        "language_btn": "🌐  Bhasha: {name}",
        # Sidebar and header
        "new_chat_btn": "＋  Nayi Chat",
        "history_label": "PURANI CHATS",
        "clear_chat_btn": "▤  Current Chat Clear Karo",
        "voice_on": "🔊  Voice: Chalu",
        "voice_off": "🔇  Voice: Band",
        "theme_to_light": "☼  Light Mode",
        "theme_to_dark": "☾  Dark Mode",
        "header_title": "✦  Aapka chhota genius aa gaya!",
        # Chat area
        "send_btn": "➤  Bhejo",
        "you_label": "Aap",
        "welcome_title": "Hey! Main JUGNU hoon",
        "welcome_prompt": "Aaj aap kya explore karna chahenge?",
        # Status line
        "status_ready": "Taiyaar",
        "status_offline": "Ollama offline hai",
        "status_thinking": "Soch raha hoon…",
        "status_save_error": "History save nahi ho payi: {error}",
        # Dialogs
        "clear_dialog_title": "Current Chat Clear Karo",
        "clear_dialog_message": "Is current chat ko history se permanently clear kar dein?",
        # Replies shown when something goes wrong
        "error_empty_reply": "Sorry, mujhe empty response mila. Ek baar phir try karo.",
        "error_timeout": ("Response mein zyada time lag raha hai. "
                          "Ollama/model load check karke dobara try karo."),
        "error_connection": ("Ollama se connect nahi ho pa raha. "
                             "Check karo ki Ollama running hai aur model installed hai."),
        "error_generic": "Error: {error}",
        # Answered locally, without calling the model
        "time_answer": "Abhi local date aur time hai: {when}",
        # Added to the system prompt so the model replies in this language
        "prompt_language_rule": ("Always answer in Hinglish: Hindi written in the English (Roman) "
                                 "alphabet, mixed naturally with common English words, the way "
                                 "people chat in India. Never use Devanagari script. "),
    },
}

SYSTEM_PROMPT_INTRO = (
    "You are JUGNU, a helpful, friendly personal AI assistant. "
    "Give clear, concise answers by default (usually 2-5 sentences). "
    "Use easy language. If more detail is needed, provide it. "
)
SYSTEM_PROMPT_CLOCK = (
    "Current local date and time: {now}. "
    "For date/time questions, use this exact current context; never guess."
)


def normalize_language(value):
    """Return `value` if it is a known language code, otherwise the default."""
    if isinstance(value, str) and value in STRINGS:
        return value
    return DEFAULT_LANGUAGE


def next_language(current):
    """The language after `current` in LANGUAGES, wrapping around."""
    current = normalize_language(current)
    return LANGUAGES[(LANGUAGES.index(current) + 1) % len(LANGUAGES)]


def get_string(language, key, **kwargs):
    """Look up `key` in `language`, filling in {placeholders} from kwargs.

    A key missing from the chosen language falls back to English, and a key
    missing everywhere returns the key itself, so the UI never crashes on text.
    """
    text = STRINGS[normalize_language(language)].get(key)
    if text is None:
        text = STRINGS[DEFAULT_LANGUAGE].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def build_system_prompt(language, now_text):
    """System prompt for the model: persona, reply-language rule, and the clock."""
    return (SYSTEM_PROMPT_INTRO
            + get_string(language, "prompt_language_rule")
            + SYSTEM_PROMPT_CLOCK.format(now=now_text))