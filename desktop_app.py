import tkinter as tk
from tkinter import messagebox
from tkinter import font as tkfont
import math
from datetime import datetime
import json
import threading
import requests
import uuid
import os
import tempfile

from strings import build_system_prompt, get_string, next_language, normalize_language
from tts import TTSManager
from assistant import is_time_question as detect_time_question

APP_TITLE = "JUGNU | Just an Unusually Genius Neural Utility"
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.2:3b"
HISTORY_FILE = "jugnu_history.json"
SETTINGS_FILE = "jugnu_settings.json"

LIGHT = {
    "bg": "#F7F4FF", "sidebar": "#EEE8FF", "panel": "#FFFFFF",
    "text": "#27213B", "muted": "#756B91", "accent": "#8B5CF6",
    "accent2": "#EC4899", "user": "#E3DCFF", "assistant": "#F0EAFB",
    "entry": "#FFFFFF", "border": "#D9CFF5", "danger": "#FCE7F3"
}
DARK = {
    "bg": "#191728", "sidebar": "#211D35", "panel": "#28223D",
    "text": "#F4EEFF", "muted": "#B7A9D8", "accent": "#8B6CF0",
    "accent2": "#D946A6", "user": "#34365A", "assistant": "#2A2440",
    "entry": "#2A2440", "border": "#463A66", "danger": "#4B2A40"
}

def local_datetime_text():
    # Uses the Windows system's configured local timezone.
    now = datetime.now().astimezone()
    return now.strftime("%A, %d %B %Y, %I:%M:%S %p %Z")

class JugnuApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1200x760")
        self.root.minsize(850, 570)

        self.chats = self.load_history()
        self.current_id = None
        self.draft_chat = None  # Unsaved empty chat; saved only after first message.
        self.busy = False
        self.dark_mode = self.load_settings()
        self.colors = DARK if self.dark_mode else LIGHT
        self.tts = TTSManager()  # Offline voice output; runs on its own thread.
        self.voice_enabled = self.load_voice_setting()
        self.language = self.load_language_setting()
        self._status = ("status_ready", {})  # Remembered so the status line can be re-translated.
        self.read_buttons = []  # "Read aloud" buttons currently on screen
        self.stop_shown = False  # is the header Stop button visible?
        self.bubble_font = tkfont.Font(family="Segoe UI", size=10)
        self.char_w = max(self.bubble_font.measure("0"), 1)
        self.bubble_items = []
        self._resize_timer = None
        self.canvas_width = None

        self.build_ui()
        if self.chats:
            self.current_id = self.chats[-1]["id"]  # Reopen most recent saved conversation.
        else:
            self.make_draft()
        self.apply_language()
        self.apply_theme()
        self.root.after(250, self.warm_up)
        self.poll_speech()

    def load_history(self):
        """Load valid, non-empty conversations from the history file."""
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as history_file:
                data = json.load(history_file)

            if not isinstance(data, list):
                return []

            valid_chats = []
            seen_ids = set()

            for chat in data:
                if not isinstance(chat, dict):
                    continue

                chat_id = chat.get("id")
                messages = chat.get("messages")

                if not isinstance(chat_id, str) or not chat_id.strip():
                    continue
                if chat_id in seen_ids:
                    continue
                if not isinstance(messages, list):
                    continue

                valid_messages = []
                for message in messages:
                    if not isinstance(message, dict):
                        continue

                    role = message.get("role")
                    content = message.get("content")

                    if role not in ("user", "assistant"):
                        continue
                    if not isinstance(content, str) or not content.strip():
                        continue

                    valid_messages.append({
                        "role": role,
                        "content": content
                    })

                # Empty conversations should never appear in saved history.
                if not valid_messages:
                    continue

                chat["messages"] = valid_messages
                title = chat.get("title")
                chat["title"] = title.strip() if isinstance(title, str) and title.strip() else "New Chat"

                valid_chats.append(chat)
                seen_ids.add(chat_id)

            return valid_chats

        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def save_history(self):
        """Save non-empty conversations atomically to avoid partial JSON files."""
        saved_chats = [
            chat for chat in self.chats
            if isinstance(chat, dict)
            and isinstance(chat.get("messages"), list)
            and any(
                isinstance(message, dict)
                and message.get("role") in ("user", "assistant")
                and isinstance(message.get("content"), str)
                and message["content"].strip()
                for message in chat["messages"]
            )
        ]

        history_path = os.path.abspath(HISTORY_FILE)
        history_dir = os.path.dirname(history_path)
        temp_path = None

        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(saved_chats, f, ensure_ascii=False, indent=2)
        except OSError as e:
            self.set_status("status_save_error", error=e)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=history_dir,
                suffix=".tmp",
                delete=False
            ) as temp_file:
                temp_path = temp_file.name
                json.dump(saved_chats, temp_file, ensure_ascii=False, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            # The temporary file is in the same directory, so replacement is atomic.
            os.replace(temp_path, history_path)
            temp_path = None

        except (OSError, TypeError, ValueError) as error:
            self.set_status(f"Could not save history: {error}")

        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def load_settings(self):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return bool(json.load(f).get("dark_mode", True))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return True

    def load_voice_setting(self):
        # Voice output is off by default; the choice is remembered between launches.
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return bool(json.load(f).get("voice_enabled", False))
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            return False

    def load_language_setting(self):
        # English by default; an unknown or damaged value also falls back to English.
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return normalize_language(json.load(f).get("language"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            return normalize_language(None)

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"dark_mode": self.dark_mode, "voice_enabled": self.voice_enabled,
                           "language": self.language}, f)
        except OSError:
            pass

    def build_ui(self):
        # Visible text is filled in by apply_language(), so it can be switched at runtime.
        self.main = tk.Frame(self.root)
        self.main.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(self.main, width=230)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.brand = tk.Label(self.sidebar, text="🤖  JUGNU", font=("Segoe UI", 22, "bold"),
                              anchor="w", padx=18, pady=18)
        self.brand.pack(fill="x")
        self.tagline = tk.Label(self.sidebar, text="Just an Unusually Genius\nNeural Utility",
                                font=("Segoe UI", 9), justify="left", anchor="w", padx=20)
        self.tagline.pack(fill="x", pady=(0, 18))

        self.new_btn = tk.Button(self.sidebar, command=self.new_chat,
                                 font=("Segoe UI", 10, "bold"), relief="flat", pady=12)
        self.new_btn.pack(fill="x", padx=12, pady=(0, 18))

        self.history_label = tk.Label(self.sidebar, font=("Segoe UI", 9, "bold"),
                                      anchor="w", padx=18)
        self.history_label.pack(fill="x")

        self.history_list = tk.Listbox(self.sidebar, relief="flat", borderwidth=0,
                                       font=("Segoe UI", 9), activestyle="none")
        self.history_list.pack(fill="both", expand=True, padx=8, pady=8)
        self.history_list.bind("<<ListboxSelect>>", self.select_chat)

        self.clear_btn = tk.Button(self.sidebar, command=self.clear_chat,
                                   relief="flat", pady=10)
        self.clear_btn.pack(fill="x", padx=12, pady=(4, 8))
        self.voice_btn = tk.Button(self.sidebar, command=self.toggle_voice,
                                   relief="flat", pady=10)
        self.voice_btn.pack(fill="x", padx=12, pady=(0, 8))
        if not self.tts.available:
            self.voice_btn.configure(state="disabled")  # pyttsx3 not installed
        self.language_btn = tk.Button(self.sidebar, command=self.toggle_language,
                                      relief="flat", pady=10)
        self.language_btn.pack(fill="x", padx=12, pady=(0, 8))
        self.theme_btn = tk.Button(self.sidebar, command=self.toggle_theme,
                                   relief="flat", pady=10)
        self.theme_btn.pack(fill="x", padx=12, pady=(0, 12))

        self.content = tk.Frame(self.main)
        self.content.pack(side="left", fill="both", expand=True)

        self.header = tk.Frame(self.content, height=64)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)
        self.header_title = tk.Label(self.header, font=("Segoe UI", 15, "bold"),
                                     anchor="w", padx=22)
        self.header_title.pack(side="left", fill="y")
        self.status = tk.Label(self.header, font=("Segoe UI", 9, "bold"),
                               anchor="e", padx=18)
        self.status.pack(side="right", fill="y")
        # Shown only while speech is playing (see poll_speech); packed after status, so it sits left of it.
        self.stop_btn = tk.Button(self.header, text="⏹  Stop", command=self.stop_speaking,
                                  relief="flat", font=("Segoe UI", 9, "bold"), padx=12, pady=4)

        self.chat_area = tk.Frame(self.content)
        self.chat_area.pack(fill="both", expand=True, padx=12, pady=12)
        self.canvas = tk.Canvas(self.chat_area, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.chat_area, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.messages_frame = tk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.messages_frame, anchor="nw")
        self.messages_frame.bind("<Configure>", self.on_frame_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind_all("<Button-4>", self.on_mousewheel)
        self.canvas.bind_all("<Button-5>", self.on_mousewheel)

        self.bottom = tk.Frame(self.content)
        self.bottom.pack(fill="x", padx=12, pady=(0, 12))
        self.input_box = tk.Text(self.bottom, height=2, wrap="word", font=("Segoe UI", 11),
                                 relief="flat", padx=10, pady=10, undo=True)
        self.input_box.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.input_box.bind("<Control-Return>", self.send_message)
        self.send_btn = tk.Button(self.bottom, command=self.send_message,
        self.input_box.bind("<Return>", self.send_message)
        self.input_box.bind("<Shift-Return>", lambda event: None)
        self.send_btn = tk.Button(self.bottom, text="➤  Send", command=self.send_message,
                                  relief="flat", font=("Segoe UI", 10, "bold"), padx=18, pady=12)
        self.send_btn.pack(side="right")

    def on_frame_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def on_canvas_configure(self, event):
        self.canvas_width = event.width
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        if self._resize_timer:
            try:
                self.root.after_cancel(self._resize_timer)
            except Exception:
                pass
        self._resize_timer = self.root.after(100, self.recalculate_bubbles)

    def recalculate_bubbles(self):
        canvas_w = getattr(self, "canvas_width", None) or self.canvas.winfo_width()
        if canvas_w < 100 or not self.bubble_items:
            return
        max_bubble_px = min(720, max(280, canvas_w - 120))
        max_cols = max(20, max_bubble_px // self.char_w)

        # Phase 1: Update widths so Tk wraps lines to the new dimension
        for bubble, txt, orig_text in self.bubble_items:
            try:
                lines = orig_text.splitlines() or [""]
                max_line_px = max(self.bubble_font.measure(l) for l in lines)
                cols = max(18, min(max_cols, max(1, math.ceil(max_line_px / self.char_w))))
                txt.configure(state="normal", width=cols)
            except tk.TclError:
                pass

        # Update geometry so displaylines accurately reflects the new width
        self.root.update_idletasks()

        # Phase 2: Set exact height matching display line count
        for bubble, txt, orig_text in self.bubble_items:
            try:
                dlines = txt.count("1.0", "end", "displaylines")
                h = max(1, dlines[0] - 1 if (dlines and orig_text.endswith("\n")) else (dlines[0] if dlines else 1))
                txt.configure(height=h, state="disabled")
            except tk.TclError:
                pass

        self.root.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def on_mousewheel(self, event):
        try:
            target = self.canvas
            if event.widget == self.history_list:
                target = self.history_list
            elif event.widget == self.input_box:
                target = self.input_box

            if event.num == 4:
                target.yview_scroll(-1, "units")
            elif event.num == 5:
                target.yview_scroll(1, "units")
            elif event.delta:
                delta = event.delta
                if abs(delta) >= 120:
                    target.yview_scroll(int(-1 * (delta / 120)), "units")
                else:
                    target.yview_scroll(int(-1 * delta), "units")
            return "break"
        except tk.TclError:
            pass

    def apply_theme(self):
        c = self.colors
        widgets = [
            (self.root, c["bg"]), (self.main, c["bg"]), (self.sidebar, c["sidebar"]),
            (self.content, c["bg"]), (self.header, c["accent"]), (self.chat_area, c["bg"]),
            (self.canvas, c["bg"]), (self.messages_frame, c["bg"]), (self.bottom, c["bg"])
        ]
        for widget, color in widgets:
            widget.configure(bg=color)
        for widget in [self.brand, self.tagline, self.history_label]:
            widget.configure(bg=c["sidebar"], fg=c["text"])
        self.brand.configure(fg=c["accent"])
        self.tagline.configure(fg=c["muted"])
        self.history_label.configure(fg=c["muted"])
        self.header_title.configure(bg=c["accent"], fg="white")
        self.status.configure(bg=c["accent"], fg="#D1FAE5")
        self.stop_btn.configure(bg=c["accent2"], fg="white", activebackground=c["danger"],
                                activeforeground=c["accent2"], cursor="hand2")
        self.history_list.configure(bg=c["sidebar"], fg=c["text"],
                                    selectbackground=c["accent"], selectforeground="white")
        for btn in [self.new_btn, self.theme_btn, self.voice_btn, self.language_btn]:
            btn.configure(bg=c["accent"], fg="white", activebackground=c["accent2"],
                          activeforeground="white", cursor="hand2")
        self.voice_btn.configure(text=self.voice_button_text())
        self.clear_btn.configure(bg=c["danger"], fg=c["accent2"], activebackground=c["danger"],
                                 activeforeground=c["text"], cursor="hand2")
        self.input_box.configure(bg=c["entry"], fg=c["text"], insertbackground=c["text"])
        self.send_btn.configure(bg=c["accent"], fg="white", activebackground=c["accent2"],
                                activeforeground="white", cursor="hand2")
        self.theme_btn.configure(text=self.theme_button_text())
        self.refresh_history_list()
        self.display_chat()

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.colors = DARK if self.dark_mode else LIGHT
        self.save_settings()
        self.apply_theme()

    def toggle_voice(self):
        self.voice_enabled = not self.voice_enabled
        if not self.voice_enabled:
            self.tts.stop()  # Muting silences the current reply immediately.
        self.voice_btn.configure(text=self.voice_button_text())
        self.save_settings()

    def stop_speaking(self):
        self.tts.stop()
        self.poll_speech(reschedule=False)  # hide the Stop button right away

    def read_aloud(self, text):
        # Reads exactly this message. Works even when the sidebar Voice toggle is off,
        # because the user asked for it explicitly. Replaces anything already being read.
        if not self.tts.available:
            return
        self.tts.stop()
        self.tts.speak(text)
        self.poll_speech(reschedule=False)

    def poll_speech(self, reschedule=True):
        # Keep the Stop button and the Read aloud buttons in step with the speech engine.
        speaking = self.tts.speaking
        if speaking and not self.stop_shown:
            self.stop_btn.pack(side="right", padx=(0, 4))
            self.stop_shown = True
        elif not speaking and self.stop_shown:
            self.stop_btn.pack_forget()
            self.stop_shown = False
        state = "normal" if self.tts.available else "disabled"
        for btn in self.read_buttons:
            try:
                btn.configure(state=state)
            except tk.TclError:
                pass  # its bubble was already redrawn
        if reschedule:
            self.root.after(200, self.poll_speech)

    def on_close(self):
        if self._resize_timer:
            try:
                self.root.after_cancel(self._resize_timer)
            except Exception:
                pass
        self.tts.shutdown()
        self.root.destroy()

    def t(self, key, **kwargs):
        """Look up a user-facing string in the currently selected language."""
        return get_string(self.language, key, **kwargs)

    def voice_button_text(self):
        return self.t("voice_on" if self.voice_enabled else "voice_off")

    def theme_button_text(self):
        return self.t("theme_to_light" if self.dark_mode else "theme_to_dark")

    def toggle_language(self):
        self.language = next_language(self.language)
        self.save_settings()
        self.apply_language()
        self.display_chat()  # Redraw so the welcome screen and "You" labels switch too.

    def apply_language(self):
        # Set every piece of visible text from the strings dictionary.
        self.new_btn.configure(text=self.t("new_chat_btn"))
        self.history_label.configure(text=self.t("history_label"))
        self.clear_btn.configure(text=self.t("clear_chat_btn"))
        self.voice_btn.configure(text=self.voice_button_text())
        self.language_btn.configure(text=self.t("language_btn", name=self.t("language_name")))
        self.theme_btn.configure(text=self.theme_button_text())
        self.header_title.configure(text=self.t("header_title"))
        self.send_btn.configure(text=self.t("send_btn"))
        key, kwargs = self._status
        self.set_status(key, **kwargs)

    def refresh_history_list(self):
        selected = self.current_id
        self.history_list.delete(0, "end")
        for chat in reversed(self.chats):
            title = chat.get("title", "New Chat")
            self.history_list.insert("end", "  ◌  " + title[:34])
        if selected:
            for idx, chat in enumerate(reversed(self.chats)):
                if chat.get("id") == selected:
                    self.history_list.selection_set(idx)
                    break

    def make_draft(self):
        self.draft_chat = {"id": str(uuid.uuid4()), "title": "New Chat", "messages": []}
        self.current_id = self.draft_chat["id"]

    def new_chat(self):
        # A blank chat is temporary. It must not create a history entry until a message is sent.
        self.tts.stop()
        self.make_draft()
        self.refresh_history_list()
        self.display_chat()
        self.input_box.focus_set()

    def current_chat(self):
        if self.draft_chat and self.draft_chat.get("id") == self.current_id:
            return self.draft_chat
        for chat in self.chats:
            if chat.get("id") == self.current_id:
                return chat
        return None

    def select_chat(self, _event=None):
        selection = self.history_list.curselection()
        if not selection:
            return
        index = len(self.chats) - 1 - selection[0]
        if 0 <= index < len(self.chats):
            self.tts.stop()
            self.current_id = self.chats[index]["id"]
            self.draft_chat = None
            self.display_chat()

    def clear_chat(self):
        chat = self.current_chat()
        if not chat or not chat.get("messages"):
            # Nothing saved to clear; leave the empty draft alone.
            return
        if not messagebox.askyesno(self.t("clear_dialog_title"), self.t("clear_dialog_message")):
            return
        self.tts.stop()
        self.chats = [saved for saved in self.chats if saved.get("id") != chat.get("id")]
        self.draft_chat = None
        self.make_draft()
        self.save_history()
        self.refresh_history_list()
        self.display_chat()

    def display_chat(self):
        self.read_buttons = []
        self.bubble_items.clear()
        for child in self.messages_frame.winfo_children():
            child.destroy()
        chat = self.current_chat()
        messages = chat.get("messages", []) if chat else []
        if not messages:
            self.show_welcome()
        else:
            for msg in messages:
                self.add_bubble(msg.get("role"), msg.get("content", ""))
        self.root.after(50, lambda: self.canvas.yview_moveto(1.0))

    def show_welcome(self):
        # Welcome splash shown on launch and for each empty New Chat.
        c = self.colors
        wrapper = tk.Frame(self.messages_frame, bg=c["bg"])
        wrapper.pack(fill="both", expand=True, pady=24)

        image_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jugnu_bot.png")
        try:
            self.welcome_photo = tk.PhotoImage(file=image_path)
            # Keep it compact in the chat viewport.
            factor = max(1, int(max(self.welcome_photo.width() / 360,
                                    self.welcome_photo.height() / 260)))
            if factor > 1:
                self.welcome_photo = self.welcome_photo.subsample(factor, factor)
            tk.Label(wrapper, image=self.welcome_photo, bg=c["bg"]).pack(pady=(0, 10))
        except (tk.TclError, OSError):
            # Friendly fallback if the companion image hasn't been copied beside the script.
            tk.Label(wrapper, text="🤖", font=("Segoe UI Emoji", 76),
                     bg=c["bg"], fg=c["accent"]).pack(pady=(10, 18))

        tk.Label(wrapper, text=self.t("welcome_title"),
                 font=("Segoe UI", 23, "bold"), bg=c["bg"], fg=c["text"]).pack(pady=(4, 5))
        tk.Label(wrapper, text="Just an Unusually Genius Neural Utility",
                 font=("Segoe UI", 12), bg=c["bg"], fg=c["muted"]).pack(pady=(0, 10))
        tk.Label(wrapper, text=self.t("welcome_prompt"),
                 font=("Segoe UI", 12), bg=c["bg"], fg=c["accent"]).pack()

    def copy_to_clipboard(self, text, button):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            success_fg = "#10B981" if self.dark_mode else "#059669"
            button.configure(text="✓ Copied!", fg=success_fg)
            def revert():
                try:
                    button.configure(text="⧉ Copy", fg=self.colors["muted"], bg=button.master["bg"])
                except tk.TclError:
                    pass
            self.root.after(1500, revert)
        except Exception:
            pass

    def add_bubble(self, role, text):
        c = self.colors
        is_user = role == "user"
        row = tk.Frame(self.messages_frame, bg=c["bg"])
        row.pack(fill="x", pady=7, padx=8)
        bubble = tk.Frame(row, bg=c["user"] if is_user else c["assistant"])
        bubble.pack(side="right" if is_user else "left", padx=(40, 0) if is_user else (0, 40))
        name = self.t("you_label") if is_user else "🤖 JUGNU"
        tk.Label(bubble, text=name, bg=bubble["bg"], fg=c["accent"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", padx=12, pady=(8, 1))
        tk.Label(bubble, text=text, bg=bubble["bg"], fg=c["text"],
                 font=("Segoe UI", 10), justify="left", anchor="w",
                 wraplength=680).pack(fill="x", padx=12, pady=(1, 10))

        header = tk.Frame(bubble, bg=bubble["bg"])
        header.pack(fill="x", padx=12, pady=(8, 2))

        name = "You" if is_user else "🤖 JUGNU"
        name_lbl = tk.Label(header, text=name, bg=bubble["bg"], fg=c["accent"],
                            font=("Segoe UI", 9, "bold"), anchor="w")
        name_lbl.pack(side="left")

        # Per-message Read aloud button (next to name/copy for assistant messages)
        read_btn = None
        if not is_user:
            read_btn = tk.Button(header, text="🔊", command=lambda t=text: self.read_aloud(t),
                                 relief="flat", bd=0, font=("Segoe UI Emoji", 10), cursor="hand2",
                                 bg=bubble["bg"], fg=c["accent"], activebackground=bubble["bg"],
                                 activeforeground=c["accent2"], disabledforeground=c["muted"],
                                 state="normal" if self.tts.available else "disabled")
            read_btn.pack(side="right", padx=(4, 0))
            self.read_buttons.append(read_btn)

        copy_btn = tk.Button(header, text="⧉ Copy", font=("Segoe UI", 8, "bold"),
                             relief="flat", bd=0, highlightthickness=0,
                             bg=bubble["bg"], fg=c["muted"],
                             highlightbackground=bubble["bg"],
                             activebackground=c["border"], activeforeground=c["accent"],
                             cursor="hand2", padx=6, pady=1)
        copy_btn.pack(side="right", padx=(8, 0))
        copy_btn.configure(command=lambda t=text, b=copy_btn: self.copy_to_clipboard(t, b))

        hover_bg = c["border"]

        def on_btn_enter(_event):
            try:
                if "Copied" not in copy_btn.cget("text"):
                    copy_btn.configure(fg=c["accent"], bg=hover_bg)
            except tk.TclError:
                pass

        def on_btn_leave(_event):
            try:
                if "Copied" not in copy_btn.cget("text"):
                    copy_btn.configure(fg=c["muted"], bg=bubble["bg"])
                else:
                    copy_btn.configure(bg=bubble["bg"])
            except tk.TclError:
                pass

        copy_btn.bind("<Enter>", on_btn_enter)
        copy_btn.bind("<Leave>", on_btn_leave)

        canvas_w = getattr(self, "canvas_width", None) or self.canvas.winfo_width()
        if canvas_w < 200:
            canvas_w = 700
        max_bubble_px = min(720, max(280, canvas_w - 120))
        max_cols = max(20, max_bubble_px // self.char_w)

        lines = text.splitlines() or [""]
        max_line_px = max(self.bubble_font.measure(l) for l in lines)
        calc_cols = max(18, min(max_cols, max(1, math.ceil(max_line_px / self.char_w))))

        txt = tk.Text(bubble, font=self.bubble_font, wrap="word", width=calc_cols,
                      relief="flat", bd=0, highlightthickness=0,
                      bg=bubble["bg"], fg=c["text"],
                      selectbackground=c["accent"], selectforeground="white",
                      inactiveselectbackground=c["accent"], cursor="xterm")
        txt.insert("1.0", text)
        txt.pack(fill="x", padx=12, pady=(2, 10))

        # Forward mouse wheel events so scrolling over bubbles scrolls the canvas
        for w in ([row, bubble, header, name_lbl, copy_btn, txt] + ([read_btn] if read_btn else [])):
            w.bind("<MouseWheel>", self.on_mousewheel)
            w.bind("<Button-4>", self.on_mousewheel)
            w.bind("<Button-5>", self.on_mousewheel)

        def copy_selection(_event=None):
            try:
                sel = txt.get("sel.first", "sel.last")
                if sel:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(sel)
                    self.root.update()
                    return "break"
            except tk.TclError:
                pass

        for key in ("<Control-c>", "<Control-C>", "<Command-c>", "<Command-C>"):
            txt.bind(key, copy_selection)

        def select_all(_event=None):
            txt.tag_add("sel", "1.0", "end - 1c")
            return "break"

        for key in ("<Control-a>", "<Control-A>", "<Command-a>", "<Command-A>"):
            txt.bind(key, select_all)

        menu = tk.Menu(txt, tearoff=0)
        menu.add_command(label="Copy Selection", command=copy_selection)
        menu.add_command(label="Select All", command=select_all)
        menu.add_command(label="Copy All", command=lambda: self.copy_to_clipboard(text, copy_btn))

        def show_context_menu(event):
            try:
                has_sel = bool(txt.tag_ranges("sel"))
                menu.entryconfigure("Copy Selection", state="normal" if has_sel else "disabled")
                menu.tk_popup(event.x_root, event.y_root)
            except tk.TclError:
                pass
            finally:
                try:
                    menu.grab_release()
                except tk.TclError:
                    pass

        txt.bind("<Button-3>", show_context_menu)
        txt.bind("<Button-2>", show_context_menu)

        self.root.update_idletasks()
        dlines = txt.count("1.0", "end", "displaylines")
        h = max(1, dlines[0] - 1 if (dlines and text.endswith("\n")) else (dlines[0] if dlines else 1))
        txt.configure(height=h, state="disabled")

        self.bubble_items.append((bubble, txt, text))

    def set_status(self, key, **kwargs):
        # Store the key (not the text) so a language switch can re-translate the status line.
        self._status = (key, kwargs)
        self.status.configure(text="• " + self.t(key, **kwargs))

    def warm_up(self):
        def task():
            try:
                requests.post(OLLAMA_URL, json={
                    "model": MODEL, "messages": [{"role": "user", "content": "Reply with OK."}],
                    "stream": False, "keep_alive": "10m",
                    "options": {"num_predict": 3}
                }, timeout=90)
                self.root.after(0, lambda: self.set_status("status_ready"))
            except requests.RequestException:
                self.root.after(0, lambda: self.set_status("status_offline"))
        threading.Thread(target=task, daemon=True).start()

    def is_time_question(self, text):
        return detect_time_question(text)

    def send_message(self, _event=None):
        if self.busy:
            return "break"
        user_text = self.input_box.get("1.0", "end").strip()
        if not user_text:
            return "break"
        self.tts.stop()  # A new message interrupts any reply still being read aloud.
        chat = self.current_chat()
        if not chat:
            self.make_draft()
            chat = self.current_chat()
        if self.draft_chat and chat.get("id") == self.draft_chat.get("id"):
            self.chats.append(self.draft_chat)
            self.draft_chat = None
        if chat.get("title") == "New Chat":
            chat["title"] = user_text[:34]
        chat["messages"].append({"role": "user", "content": user_text})
        self.input_box.delete("1.0", "end")
        self.add_bubble("user", user_text)
        self.refresh_history_list()
        self.save_history()
        self.busy = True
        self.send_btn.configure(state="disabled")
        self.set_status("status_thinking")

        # Answer clock/date questions locally for accuracy and speed—no model call required.
        if self.is_time_question(user_text):
            answer = self.t("time_answer", when=local_datetime_text())
            self.finish_answer(answer, chat["id"])
            return "break"

        threading.Thread(target=self.ask_ollama, args=(chat["id"],), daemon=True).start()
        return "break"

    def ask_ollama(self, chat_id):
        language = self.language  # The prompt and any error text use the language chosen at send time.
        try:
            chat = next((c for c in self.chats if c.get("id") == chat_id), None)
            if not chat:
                # The conversation may have been cleared while the request was running.
                self.root.after(0, lambda: self.finish_answer(None, chat_id))
                return
            # Keep recent context only, to reduce prompt size and improve latency.
            recent = chat.get("messages", [])[-10:]
            messages = [{
                "role": "system",
                "content": build_system_prompt(language, local_datetime_text())
            }]
            messages.extend({"role": m["role"], "content": m["content"]} for m in recent)
            response = requests.post(OLLAMA_URL, json={
                "model": MODEL,
                "messages": messages,
                "stream": False,
                "keep_alive": "10m",
                "options": {"num_predict": 256, "temperature": 0.6}
            }, timeout=180)
            response.raise_for_status()
            answer = response.json().get("message", {}).get("content", "").strip()
            if not answer:
                answer = get_string(language, "error_empty_reply")
        except requests.Timeout:
            answer = get_string(language, "error_timeout")
        except requests.ConnectionError:
            answer = get_string(language, "error_connection")
        except (requests.RequestException, ValueError) as e:
            answer = get_string(language, "error_generic", error=e)
        self.root.after(0, lambda: self.finish_answer(answer, chat_id))

    def finish_answer(self, answer, chat_id=None):
        chat = self.current_chat()
        if chat_id:
            chat = next((c for c in self.chats if c.get("id") == chat_id), None)
        if chat and isinstance(answer, str) and answer.strip():
            chat["messages"].append({"role": "assistant", "content": answer})
            self.save_history()
        # Only display if the user is still viewing the chat that received the answer.
        if chat and chat.get("id") == self.current_id:
            self.add_bubble("assistant", answer)
            self.canvas.yview_moveto(1.0)
            if self.voice_enabled:
                self.tts.speak(answer)
        self.busy = False
        self.send_btn.configure(state="normal")
        self.set_status("status_ready")
        self.refresh_history_list()

if __name__ == "__main__":
    root = tk.Tk()
    app = JugnuApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()