"""Tests for responsive message bubble wrapping and window resize re-wrapping."""

import time
import types
import tkinter as tk
import pytest

from desktop_app import JugnuApp


@pytest.fixture
def tk_app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(JugnuApp, "warm_up", lambda self: None)
    monkeypatch.setattr("desktop_app.TTSManager", lambda *a, **k: types.SimpleNamespace(
        available=False,
        speaking=False,
        voices=[],
        stop=lambda: None,
        speak=lambda _t: None,
        apply_settings=lambda *_a: None,
        shutdown=lambda: None,
    ))
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


def apply_canvas_width(app, root, window_width, window_height=650):
    """Simulate resizing the window and running any pending resize recalculation."""
    root.geometry(f"{window_width}x{window_height}")
    root.update_idletasks()
    canvas_w = max(200, window_width - 270)
    app.on_canvas_configure(types.SimpleNamespace(width=canvas_w))
    if app._resize_timer:
        root.after_cancel(app._resize_timer)
        app._resize_timer = None
    app.recalculate_bubbles()
    root.update_idletasks()
    return canvas_w


def test_max_bubble_width_scales_with_canvas_and_caps_at_720(tk_app):
    app, _root = tk_app

    # Narrow / below-minimum canvas never exceeds chrome budget (~100 px)
    narrow_w = app.max_bubble_width_px(320)
    assert narrow_w <= 220

    # Minimum window width (850 px -> ~580 px canvas) stays proportional and safely inside
    min_w = app.max_bubble_width_px(580)
    assert 350 <= min_w <= 480

    # Normal window width (1200 px -> ~930 px canvas) stays readable
    normal_w = app.max_bubble_width_px(930)
    assert 620 <= normal_w <= 720

    # Maximised window stays capped at 720 px
    assert app.max_bubble_width_px(1400) == 720


def test_compute_bubble_cols_never_overflows_on_high_dpi_char_width(tk_app, monkeypatch):
    app, _root = tk_app
    monkeypatch.setattr(app, "char_w", 26)
    cols = app.compute_bubble_cols("A" * 200, canvas_w=580)
    assert cols * app.char_w <= app.max_bubble_width_px(580)


def test_bubbles_do_not_overflow_at_minimum_window_size(tk_app):
    app, root = tk_app
    canvas_w = apply_canvas_width(app, root, 850, 570)

    samples = [
        ("user", " ".join(["longword"] * 45)),
        ("assistant", "https://example.com/" + ("segment-" * 20)),
        ("user", "W" * 110),
        ("assistant", "Col1\tCol2\t" + ("detail " * 25)),
        ("user", "Hi"),
    ]
    for role, text in samples:
        app.add_bubble(role, text, timestamp="10:15 AM")
    root.update_idletasks()

    assert len(app.bubble_items) == len(samples)
    for idx, (bubble, txt, _orig) in enumerate(app.bubble_items):
        req_bubble_w = bubble.winfo_reqwidth()
        # Account for row horizontal padding (16) and bubble left/right offset (40)
        assert req_bubble_w + 56 <= canvas_w, f"Bubble {idx} width {req_bubble_w} overflowed canvas {canvas_w}"
        if idx < 4:
            assert int(txt.cget("height")) > 1


def test_resizing_window_rewraps_existing_messages(tk_app):
    app, root = tk_app
    long_text = " ".join(["responsive"] * 45)

    # Start at normal 1200x760 layout
    apply_canvas_width(app, root, 1200, 760)
    app.add_bubble("user", long_text, timestamp="11:00 AM")
    app.add_bubble("assistant", long_text, timestamp="11:00 AM")
    root.update_idletasks()

    normal_widths = [int(txt.cget("width")) for _, txt, _ in app.bubble_items]
    normal_heights = [int(txt.cget("height")) for _, txt, _ in app.bubble_items]

    # Shrink to minimum 850x570 layout -> columns decrease, wrapped height increases
    min_canvas_w = apply_canvas_width(app, root, 850, 570)
    small_widths = [int(txt.cget("width")) for _, txt, _ in app.bubble_items]
    small_heights = [int(txt.cget("height")) for _, txt, _ in app.bubble_items]

    for nw, sw, nh, sh, (bubble, _txt, _) in zip(
        normal_widths, small_widths, normal_heights, small_heights, app.bubble_items
    ):
        assert sw < nw
        assert sh > nh
        assert bubble.winfo_reqwidth() + 56 <= min_canvas_w

    # Expand to maximised-like 1600x900 layout -> columns widen (up to 720 px cap), height shrinks
    apply_canvas_width(app, root, 1600, 900)
    max_widths = [int(txt.cget("width")) for _, txt, _ in app.bubble_items]
    max_heights = [int(txt.cget("height")) for _, txt, _ in app.bubble_items]

    for sw, mw, sh, mh, (bubble, _txt, _) in zip(
        small_widths, max_widths, small_heights, max_heights, app.bubble_items
    ):
        assert mw > sw
        assert mh < sh
        assert bubble.winfo_reqwidth() <= 760


def test_height_only_configure_skips_redundant_resize_timer(tk_app):
    app, root = tk_app
    apply_canvas_width(app, root, 950, 650)
    assert app._resize_timer is None

    # Same width should not schedule a new recalculate timer
    app.on_canvas_configure(types.SimpleNamespace(width=app.canvas_width))
    assert app._resize_timer is None


def test_theme_toggle_after_resize_keeps_wrapped_width(tk_app):
    app, root = tk_app
    min_canvas_w = apply_canvas_width(app, root, 850, 570)
    long_msg = " ".join(["wrapping"] * 40)
    app.current_chat()["messages"].append({"role": "assistant", "content": long_msg, "time": "12:00 PM"})
    app.toggle_theme()
    root.update_idletasks()

    assert len(app.bubble_items) == 1
    bubble, txt, _ = app.bubble_items[0]
    assert bubble.winfo_reqwidth() + 56 <= min_canvas_w
    assert int(txt.cget("height")) > 1


def test_configure_debounce_timer_triggers_rewrap(tk_app):
    app, root = tk_app
    apply_canvas_width(app, root, 1200, 760)
    app.add_bubble("assistant", " ".join(["debounce"] * 45), timestamp="12:05 PM")
    root.update_idletasks()
    before_cols = int(app.bubble_items[0][1].cget("width"))

    app.on_canvas_configure(types.SimpleNamespace(width=580))
    assert app._resize_timer is not None

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and app._resize_timer is not None:
        root.update()
        time.sleep(0.01)

    assert app._resize_timer is None
    after_cols = int(app.bubble_items[0][1].cget("width"))
    assert after_cols < before_cols
    assert app.bubble_items[0][0].winfo_reqwidth() + 56 <= 580

