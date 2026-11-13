"""Tests for Markdown in chat bubbles, using a real hidden Tk window.

If this machine has no display, they are skipped.
"""
import types
import tkinter as tk

import pytest

import desktop_app
from desktop_app import JugnuApp, DARK, LIGHT

RICH = """# Title

Some **bold**, *italic* and `inline` text.

- first
- second
  - nested

```python
def add(a, b):
    return a + b
```

> a quote

Last line."""


@pytest.fixture
def tk_app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(JugnuApp, "warm_up", lambda self: None)
    spoken = []
    monkeypatch.setattr("desktop_app.TTSManager", lambda *a, **k: types.SimpleNamespace(
        available=True, speaking=False, voices=[], stop=lambda: None,
        speak=spoken.append, apply_settings=lambda *_a: None, shutdown=lambda: None,
    ))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("No display available for Tk")
    root.withdraw()
    app = JugnuApp(root)
    app.spoken = spoken
    yield app, root
    for timer in root.tk.splitlist(root.tk.call("after", "info")):
        try:
            root.after_cancel(timer)
        except tk.TclError:
            pass
    app.welcome_photo = None
    root.destroy()


def last_text(app):
    return app.bubble_items[-1][1]


def shown(txt):
    return txt.get("1.0", "end-1c")


def copy_buttons(txt):
    return [txt.nametowidget(name) for name in txt.window_names()]


def test_assistant_markdown_is_styled(tk_app):
    app, _root = tk_app
    app.add_bubble("assistant", "A **bold** word and `code` and *slant*.")
    txt = last_text(app)
    assert shown(txt) == "A bold word and code and slant."
    for tag, word in (("bold", "bold"), ("icode", "code"), ("italic", "slant")):
        start, end = txt.tag_ranges(tag)[:2]
        assert txt.get(start, end) == word


def test_your_own_messages_are_shown_exactly_as_typed(tk_app):
    app, _root = tk_app
    app.add_bubble("user", "I typed **this** and `that`")
    assert shown(last_text(app)) == "I typed **this** and `that`"
    assert not last_text(app).tag_ranges("bold")


def test_all_block_styles_are_drawn(tk_app):
    app, _root = tk_app
    app.add_bubble("assistant", RICH)
    txt = last_text(app)
    body = shown(txt)
    assert "#" not in body and "**" not in body and "```" not in body and "`" not in body
    for tag in ("h1", "bold", "italic", "icode", "li0", "li1", "code", "codehead", "quote"):
        assert txt.tag_ranges(tag), tag
    assert "def add(a, b):\n    return a + b" in body


def test_code_block_has_a_copy_button_that_copies_the_exact_code(tk_app):
    app, root = tk_app
    code = "def add(a, b):\n    return a + b  # **keep**\n\n\nprint(add(1, 2))"
    app.add_bubble("assistant", f"Try this:\n```python\n{code}\n```\nDone.")
    (button,) = copy_buttons(last_text(app))
    assert button.cget("text") == app.t("code_copy_btn")
    button.invoke()
    assert root.clipboard_get() == code
    assert button.cget("text") == app.t("code_copied_btn")


def test_each_code_block_copies_its_own_code(tk_app):
    app, root = tk_app
    app.add_bubble("assistant", "```\nfirst\n```\ntext\n```sh\nsecond\n```")
    first, second = copy_buttons(last_text(app))
    second.invoke()
    assert root.clipboard_get() == "second"
    first.invoke()
    assert root.clipboard_get() == "first"


def test_message_copy_button_still_copies_the_original_markdown(tk_app):
    app, root = tk_app
    app.add_bubble("assistant", "**bold** text")
    header = last_text(app).master.winfo_children()[0]
    copy_all = next(w for w in header.winfo_children()
                    if isinstance(w, tk.Button) and "Copy" in w.cget("text"))
    copy_all.invoke()
    assert root.clipboard_get() == "**bold** text"


def test_copy_button_text_follows_the_language(tk_app):
    app, _root = tk_app
    app.language = "hinglish"
    app.add_bubble("assistant", "```\nx\n```")
    (button,) = copy_buttons(last_text(app))
    assert button.cget("text") == app.t("code_copy_btn") != desktop_app.get_string("en", "code_copy_btn")


def test_styling_failure_falls_back_to_plain_text(tk_app, monkeypatch):
    app, _root = tk_app

    def broken(_txt):
        raise tk.TclError("boom")
    monkeypatch.setattr(app, "configure_markdown_tags", broken)
    app.add_bubble("assistant", "**bold** and\n```\ncode\n```")
    txt = last_text(app)
    assert shown(txt) == "**bold** and\n```\ncode\n```"
    assert copy_buttons(txt) == []


def test_broken_markdown_never_crashes(tk_app):
    app, _root = tk_app
    for text in ("**", "```", "```\n", "[x](", "> ", "# ", "- ", "``` ``` ```", "\\", "*" * 500,
                 "```py\n" + "x = 1\n" * 300, "😀 **😀**", ""):
        app.add_bubble("assistant", text)
    assert len(app.bubble_items) == 13


@pytest.mark.parametrize("width", [850, 1000, 1200, 1400])
def test_long_rich_messages_are_never_cut_off(tk_app, width):
    app, root = tk_app
    root.geometry(f"{width}x760")
    root.update_idletasks()
    canvas_w = max(200, width - 270)
    app.on_canvas_configure(types.SimpleNamespace(width=canvas_w))
    if app._resize_timer:
        root.after_cancel(app._resize_timer)
        app._resize_timer = None
    long_code = "\n".join(f"    value_{n} = compute({n}) + 'a fairly long string literal here'" for n in range(40))
    for text in (RICH, RICH * 6, f"```python\n{long_code}\n```", "# H1\n## H2\n### H3\n**x**"):
        app.add_bubble("assistant", text)
    app.recalculate_bubbles()
    root.update()
    for _bubble, txt, _measure in app.bubble_items:
        assert txt.yview() == (0.0, 1.0)  # the whole message is visible: nothing scrolls inside the bubble


def test_bubbles_rewrap_when_the_window_is_resized(tk_app):
    app, root = tk_app
    app.add_bubble("assistant", ("A long sentence with **bold** words and a list below. " * 8) + "\n- item\n- item")
    root.update_idletasks()
    wide = (int(last_text(app).cget("width")), int(last_text(app).cget("height")))
    app.on_canvas_configure(types.SimpleNamespace(width=420))
    if app._resize_timer:
        root.after_cancel(app._resize_timer)
        app._resize_timer = None
    app.recalculate_bubbles()
    root.update()
    narrow = (int(last_text(app).cget("width")), int(last_text(app).cget("height")))
    assert narrow[0] < wide[0] and narrow[1] > wide[1]
    assert last_text(app).yview() == (0.0, 1.0)


def test_switching_theme_redraws_markdown_in_the_new_colours(tk_app):
    app, _root = tk_app
    chat = {"id": "x", "title": "t", "messages": [{"role": "assistant", "content": RICH}]}
    app.chats, app.current_id, app.draft_chat = [chat], "x", None
    app.display_chat()
    expected = DARK if app.dark_mode else LIGHT
    assert last_text(app).tag_cget("code", "background") == expected["code"]
    app.toggle_theme()
    expected = DARK if app.dark_mode else LIGHT
    assert last_text(app).tag_cget("code", "background") == expected["code"]
    assert last_text(app).tag_cget("icode", "background") == expected["inline_code"]


def test_read_aloud_and_voice_skip_the_markdown_symbols(tk_app):
    app, _root = tk_app
    app.read_aloud("# Title\n\nSome **bold** and `code`.")
    assert app.spoken == ["Title\n\nSome bold and code."]
    app.spoken.clear()
    app.voice_enabled = True
    chat = {"id": "y", "title": "t", "messages": [{"role": "user", "content": "hi"}]}
    app.chats, app.current_id, app.draft_chat = [chat], "y", None
    app.finish_answer("**Hello** there", "y")
    assert app.spoken == ["Hello there"]