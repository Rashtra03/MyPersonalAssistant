"""Offline text-to-speech for JUGNU.

All speech runs on one background worker thread, so the Tkinter GUI never
freezes. The public methods (speak / stop / shutdown) are safe to call from the
GUI thread; the worker never touches any widget.

If pyttsx3 or a system voice is missing, `TTSManager.available` becomes False
and every method quietly does nothing, so the app keeps working without voice.
"""
import queue
import re
import threading

try:
    import pyttsx3
except ImportError:  # JUGNU must still run when pyttsx3 is not installed
    pyttsx3 = None


def clean_for_speech(text):
    """Strip markdown, code and URLs so the voice doesn't read symbols aloud."""
    text = re.sub(r"```.*?```", " Code block omitted. ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)                # inline code
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)    # [label](url) -> label
    text = re.sub(r"https?://\S+", "link", text)
    text = re.sub(r"[*_#>~|]+", " ", text)                  # markdown symbols
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s]


class TTSManager:
    def __init__(self, rate=175, volume=1.0):
        self.available = pyttsx3 is not None
        self.rate = rate
        self.volume = volume
        self._queue = queue.Queue()
        self._generation = 0
        self._lock = threading.Lock()
        self._engine = None
        if self.available:
            threading.Thread(target=self._worker, name="jugnu-tts", daemon=True).start()

    # ---------- public API (call from the GUI thread) ----------
    def speak(self, text):
        """Queue text to be read aloud. Does nothing if TTS is unavailable."""
        if not self.available:
            return
        text = clean_for_speech(text)
        if text:
            self._queue.put((self._current_generation(), text))

    def stop(self):
        """Interrupt current speech and drop anything still queued."""
        if not self.available:
            return
        with self._lock:
            self._generation += 1
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def shutdown(self):
        """Stop speaking and let the worker thread exit."""
        self.stop()
        if self.available:
            self._queue.put(None)

    # ---------- worker thread ----------
    def _current_generation(self):
        with self._lock:
            return self._generation

    def _worker(self):
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.setProperty("volume", self.volume)
        except Exception:  # no usable speech driver / voice on this machine
            self.available = False
            return
        self._engine = engine

        active = {"gen": None}

        def on_word(name, location, length):
            # Runs inside the engine loop on THIS thread, which is the safe place
            # to call engine.stop(). If stop() was requested, cut speech mid-sentence.
            if active["gen"] is not None and active["gen"] != self._current_generation():
                try:
                    engine.stop()
                except Exception:
                    pass

        try:
            engine.connect("started-word", on_word)
        except Exception:
            pass  # driver without word events: we still stop at the next sentence

        while True:
            item = self._queue.get()
            if item is None:
                return
            gen, text = item
            for sentence in split_sentences(text):
                if gen != self._current_generation():
                    break  # interrupted before this sentence started
                active["gen"] = gen
                try:
                    engine.say(sentence)
                    engine.runAndWait()
                except Exception:
                    break
            active["gen"] = None