import json
import re
import tkinter as tk
from datetime import datetime
import pytest

import desktop_app
from desktop_app import JugnuApp, message_time_text, DARK, LIGHT, FlatButton


def is_text_label(widget):
    # On macOS the buttons are FlatButtons, which are tk.Label subclasses.
    return isinstance(widget, tk.Label) and not isinstance(widget, FlatButton)


def test_message_time_text_format():
    val = message_time_text()
    assert isinstance(val, str)
    assert re.match(r"^\d{2}:\d{2} (AM|PM)$", val), f"Unexpected format: {val}"


@pytest.fixture
def tk_app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(JugnuApp, "warm_up", lambda self: None)
    monkeypatch.setattr("desktop_app.TTSManager", lambda *a, **k: type("TTS", (), {
        "available": False,
        "speaking": False,
        "stop": lambda self: None,
        "speak": lambda self, t: None,
    })())
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("No display available for Tk")
    root.withdraw()
    app = JugnuApp(root)
    yield app, root
    for timer in root.tk.splitlist(root.tk.call("after", "info")):
        try:
            root.after_cancel(timer)
        except tk.TclError:
            pass
    app.welcome_photo = None
    root.destroy()


def test_existing_history_files_load_without_errors(tmp_path, monkeypatch):
    history_file = tmp_path / "jugnu_history.json"
    legacy_data = [
        {
            "id": "chat-legacy-1",
            "title": "Old conversation",
            "messages": [
                {"role": "user", "content": "How does history work?"},
                {"role": "assistant", "content": "It saves chats in JSON."}
            ]
        }
    ]
    history_file.write_text(json.dumps(legacy_data), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(JugnuApp, "warm_up", lambda self: None)
    monkeypatch.setattr("desktop_app.TTSManager", lambda *a, **k: type("TTS", (), {
        "available": False,
        "speaking": False,
        "stop": lambda self: None,
        "speak": lambda self, t: None,
    })())
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("No display available for Tk")
    root.withdraw()
    app = JugnuApp(root)

    assert len(app.chats) == 1
    loaded_chat = app.chats[0]
    assert loaded_chat["title"] == "Old conversation"
    for msg in loaded_chat["messages"]:
        assert "time" not in msg
        assert msg.get("time") is None

    for timer in root.tk.splitlist(root.tk.call("after", "info")):
        try:
            root.after_cancel(timer)
        except tk.TclError:
            pass
    app.welcome_photo = None
    root.destroy()


def test_history_with_time_loads_and_retains_time(tmp_path, monkeypatch):
    history_file = tmp_path / "jugnu_history.json"
    data_with_time = [
        {
            "id": "chat-timed-1",
            "title": "Timed Chat",
            "messages": [
                {"role": "user", "content": "What is the time?", "time": "09:30 AM"},
                {"role": "assistant", "content": "It is morning.", "time": "09:31 AM"}
            ]
        }
    ]
    history_file.write_text(json.dumps(data_with_time), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(JugnuApp, "warm_up", lambda self: None)
    monkeypatch.setattr("desktop_app.TTSManager", lambda *a, **k: type("TTS", (), {
        "available": False,
        "speaking": False,
        "stop": lambda self: None,
        "speak": lambda self, t: None,
    })())
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("No display available for Tk")
    root.withdraw()
    app = JugnuApp(root)

    assert len(app.chats) == 1
    loaded_msgs = app.chats[0]["messages"]
    assert loaded_msgs[0]["time"] == "09:30 AM"
    assert loaded_msgs[1]["time"] == "09:31 AM"

    for timer in root.tk.splitlist(root.tk.call("after", "info")):
        try:
            root.after_cancel(timer)
        except tk.TclError:
            pass
    app.welcome_photo = None
    root.destroy()


def test_new_messages_save_time_to_history(tk_app):
    app, root = tk_app
    app.input_box.insert("1.0", "Hello Jugnu!")
    app.send_message()

    current_chat = app.current_chat()
    assert len(current_chat["messages"]) >= 1
    user_msg = current_chat["messages"][0]
    assert "time" in user_msg
    assert re.match(r"^\d{2}:\d{2} (AM|PM)$", user_msg["time"])

    app.finish_answer("Hello! How can I help you?", current_chat["id"])
    assistant_msg = current_chat["messages"][1]
    assert "time" in assistant_msg
    assert re.match(r"^\d{2}:\d{2} (AM|PM)$", assistant_msg["time"])

    # Verify saved in jugnu_history.json
    with open(desktop_app.HISTORY_FILE, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert len(saved) >= 1
    saved_msgs = saved[0]["messages"]
    assert saved_msgs[0]["time"] == user_msg["time"]
    assert saved_msgs[1]["time"] == assistant_msg["time"]


def test_add_bubble_renders_timestamp_and_theme_colors(tk_app):
    app, root = tk_app
    app.add_bubble("user", "Hello world", timestamp="02:15 PM")

    # Find the header inside messages_frame
    rows = app.messages_frame.winfo_children()
    bubble_row = rows[-1]
    bubble_frame = bubble_row.winfo_children()[0]
    header_frame = bubble_frame.winfo_children()[0]

    labels = [w for w in header_frame.winfo_children() if is_text_label(w)]
    time_labels = [l for l in labels if l.cget("text") == "02:15 PM"]
    assert len(time_labels) == 1
    time_lbl = time_labels[0]

    # Verify colors match Dark theme
    assert time_lbl.cget("fg") == DARK["muted"]
    assert time_lbl.cget("bg") == DARK["user"]

    # Toggle to Light theme and check display_chat
    app.toggle_theme()
    rows_light = app.messages_frame.winfo_children()
    # If messages are in current_chat, display_chat redraws them
    app.current_chat()["messages"].append({"role": "user", "content": "Hello world", "time": "02:15 PM"})
    app.display_chat()

    rows_light = app.messages_frame.winfo_children()
    bubble_row_light = rows_light[-1]
    bubble_frame_light = bubble_row_light.winfo_children()[0]
    header_frame_light = bubble_frame_light.winfo_children()[0]

    labels_light = [w for w in header_frame_light.winfo_children() if is_text_label(w)]
    time_labels_light = [l for l in labels_light if l.cget("text") == "02:15 PM"]
    assert len(time_labels_light) == 1
    time_lbl_light = time_labels_light[0]

    assert time_lbl_light.cget("fg") == LIGHT["muted"]
    assert time_lbl_light.cget("bg") == LIGHT["user"]


def test_add_bubble_without_timestamp_has_no_time_label(tk_app):
    app, root = tk_app
    app.add_bubble("user", "No timestamp message", timestamp=None)

    rows = app.messages_frame.winfo_children()
    bubble_row = rows[-1]
    bubble_frame = bubble_row.winfo_children()[0]
    header_frame = bubble_frame.winfo_children()[0]

    labels = [w for w in header_frame.winfo_children() if is_text_label(w)]
    assert len(labels) == 1  # Only name_lbl ("You")
    assert labels[0].cget("text") == app.t("you_label")


def test_malformed_time_in_history_is_handled_gracefully(tmp_path, monkeypatch):
    history_file = tmp_path / "jugnu_history.json"
    data = [
        {
            "id": "chat-malformed-time",
            "title": "Chat",
            "messages": [
                {"role": "user", "content": "hi", "time": ""},
                {"role": "assistant", "content": "hello", "time": 12345},
                {"role": "user", "content": "test", "time": None},
                {"role": "assistant", "content": "valid", "time": "05:12 PM"}
            ]
        }
    ]
    history_file.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(JugnuApp, "warm_up", lambda self: None)
    monkeypatch.setattr("desktop_app.TTSManager", lambda *a, **k: type("TTS", (), {
        "available": False,
        "speaking": False,
        "stop": lambda self: None,
        "speak": lambda self, t: None,
    })())
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("No display available for Tk")
    root.withdraw()
    app = JugnuApp(root)

    loaded = app.load_history()
    msgs = loaded[0]["messages"]
    assert "time" not in msgs[0]
    assert "time" not in msgs[1]
    assert "time" not in msgs[2]
    assert msgs[3]["time"] == "05:12 PM"

    for timer in root.tk.splitlist(root.tk.call("after", "info")):
        try:
            root.after_cancel(timer)
        except tk.TclError:
            pass
    app.welcome_photo = None
    root.destroy()


def test_switching_between_old_and_new_chats_renders_correctly(tk_app):
    app, root = tk_app

    old_chat = {
        "id": "old-chat",
        "title": "Old Chat",
        "messages": [
            {"role": "user", "content": "Old question"},
            {"role": "assistant", "content": "Old answer"}
        ]
    }
    new_chat = {
        "id": "new-chat",
        "title": "New Chat",
        "messages": [
            {"role": "user", "content": "New question", "time": "11:20 AM"},
            {"role": "assistant", "content": "New answer", "time": "11:21 AM"}
        ]
    }
    app.chats = [old_chat, new_chat]
    app.refresh_history_list()

    # Open old chat
    app.current_id = "old-chat"
    app.display_chat()

    rows = app.messages_frame.winfo_children()
    assert len(rows) == 2
    for row in rows:
        header = row.winfo_children()[0].winfo_children()[0]
        labels = [w for w in header.winfo_children() if is_text_label(w)]
        # Only the sender name label, no timestamp label
        assert len(labels) == 1

    # Switch to new chat
    app.current_id = "new-chat"
    app.display_chat()

    rows = app.messages_frame.winfo_children()
    assert len(rows) == 2

    # User bubble in new chat
    user_header = rows[0].winfo_children()[0].winfo_children()[0]
    user_labels = [w for w in user_header.winfo_children() if is_text_label(w)]
    assert len(user_labels) == 2
    assert user_labels[1].cget("text") == "11:20 AM"

    # Assistant bubble in new chat
    assistant_header = rows[1].winfo_children()[0].winfo_children()[0]
    assistant_labels = [w for w in assistant_header.winfo_children() if is_text_label(w)]
    assert len(assistant_labels) == 2
    assert assistant_labels[1].cget("text") == "11:21 AM"


def test_calculator_local_reply_has_timestamp(tk_app):
    app, root = tk_app
    app.input_box.insert("1.0", "Calculate 15 + 25")
    app.send_message()

    current_chat = app.current_chat()
    assert len(current_chat["messages"]) == 2
    user_msg = current_chat["messages"][0]
    assistant_msg = current_chat["messages"][1]

    assert "time" in user_msg and re.match(r"^\d{2}:\d{2} (AM|PM)$", user_msg["time"])
    assert "time" in assistant_msg and re.match(r"^\d{2}:\d{2} (AM|PM)$", assistant_msg["time"])
    assert "40" in assistant_msg["content"]




