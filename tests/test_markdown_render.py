"""Tests for the Markdown reader (markdown_render.py). No Tk window is needed."""
import random
import time

import pytest

from markdown_render import MAX_CHARS, Seg, parse_inline, plain_text, render_markdown


def styled(text):
    """The (text, tags) pairs of a rendered message, without the copy-button pieces."""
    return [(s.text, s.tags) for s in render_markdown(text) if s.copy is None]


def tags_of(text, word):
    """Style names applied to `word` in the rendered message."""
    for seg in render_markdown(text):
        if seg.copy is None and word in seg.text:
            return seg.tags
    raise AssertionError(f"{word!r} not found")


# ---------- inline styles ----------
def test_bold_italic_and_both():
    text = "a **bold** b *italic* c ***both*** d __bold2__ e _it2_"
    assert tags_of(text, "bold") == ("bold",)
    assert tags_of(text, "italic") == ("italic",)
    assert tags_of(text, "both") == ("bolditalic",)
    assert tags_of(text, "bold2") == ("bold",)
    assert tags_of(text, "it2") == ("italic",)
    assert plain_text(text) == "a bold b italic c both d bold2 e it2"


def test_nested_styles():
    assert styled("*a **b** c*") == [("a ", ("italic",)), ("b", ("bolditalic",)), (" c", ("italic",))]
    assert tags_of("**bold with `code`**", "code") == ("bold", "icode")


def test_strikethrough_and_inline_code():
    assert tags_of("~~gone~~", "gone") == ("strike",)
    assert styled("`a*b*c`") == [("a*b*c", ("icode",))]  # nothing inside code is styled
    assert styled("`` a`b ``") == [("a`b", ("icode",))]


def test_links_show_label_and_address():
    assert styled("[docs](https://x.org/a)") == [("docs", ("link",)), (" (https://x.org/a)", ("linkurl",))]
    assert plain_text("[https://x.org](https://x.org)") == "https://x.org"  # the address is not repeated


def test_escaped_symbols_stay_literal():
    assert plain_text(r"\*not italic\* and \`not code\`") == "*not italic* and `not code`"


@pytest.mark.parametrize("text", [
    "2*3*4 = 24",                 # maths
    "x**2 + y**2",                # power
    "snake_case_name and my_var_", # identifiers
    "5 * 3 and a * b * c",        # spaces around the star
    "**unclosed bold",
    "*unclosed italic",
    "`unclosed code",
    "~~unclosed",
    "[not a link](",
    "a ** b",
])
def test_things_that_look_like_markdown_but_are_not(text):
    assert styled(text) == [(text, ())]


# ---------- blocks ----------
def test_headings():
    assert styled("# One\n## Two\n### Three\n#### Four") == [
        ("One", ("h1",)), ("\n", ()), ("Two", ("h2",)), ("\n", ()), ("Three", ("h3",)),
        ("\n", ()), ("Four", ("h3",))]
    assert plain_text("#hashtag stays") == "#hashtag stays"
    assert plain_text("## Closed heading ##") == "Closed heading"


def test_bullets_numbers_and_nesting():
    text = "- one\n* two\n+ three\n  - nested\n    - deeper\n1. first\n2) second"
    assert plain_text(text) == "• one\n• two\n• three\n◦ nested\n• deeper\n1. first\n2) second"
    assert tags_of(text, "nested") == ("li1",)
    assert tags_of(text, "deeper") == ("li2",)
    assert tags_of("- **x** y", "x") == ("bold", "li0")


def test_bold_line_is_not_a_bullet():
    assert plain_text("**Note:** careful") == "Note: careful"


def test_quote_and_rule():
    assert plain_text("> wise words") == "│ wise words"
    assert plain_text("a\n---\nb").splitlines()[1] == "─" * 28
    assert plain_text("***\n") == "─" * 28


def test_blank_lines_are_collapsed():
    assert plain_text("\n\nfirst\n\n\n\nsecond\n\n") == "first\n\nsecond"


def test_windows_line_endings():
    assert plain_text("a\r\n\r\nb") == "a\n\nb"


# ---------- code blocks ----------
def test_fenced_code_block_is_kept_exactly():
    code = "def f(x):\n    return x*2  # **not bold**\n\n\nprint(f(2))"
    segs = render_markdown("Intro\n```python\n" + code + "\n```\nOutro")
    buttons = [s for s in segs if s.copy is not None]
    assert [b.copy for b in buttons] == [code]
    body = "".join(s.text for s in segs if "code" in s.tags)
    assert body == code + "\n"
    assert "".join(s.text for s in segs if s.copy is None).splitlines()[0] == "Intro"
    assert "Outro" in plain_text("Intro\n```python\n" + code + "\n```\nOutro")


def test_code_header_names_the_language():
    assert " python " in plain_text("```python\nx=1\n```")
    assert " code " in plain_text("```\nx=1\n```")
    assert " js " in plain_text("~~~js title=a\nx\n~~~")


def test_unclosed_fence_runs_to_the_end():
    segs = render_markdown("Here:\n```py\nprint(1)\nprint(2)")
    assert [s.copy for s in segs if s.copy is not None] == ["print(1)\nprint(2)"]


def test_longer_fence_can_contain_a_shorter_one():
    code = "```\ninner\n```"
    segs = render_markdown("````md\n" + code + "\n````")
    assert [s.copy for s in segs if s.copy is not None] == [code]


def test_text_around_code_gets_a_blank_line():
    text = plain_text("before\n```\nx\n```\nafter")
    assert text.startswith("before\n\n code \nx\n\nafter")


def test_backticks_in_a_sentence_are_not_a_fence():
    assert [s for s in render_markdown("```inline``` text") if s.copy is not None] == []


def test_empty_code_block():
    segs = render_markdown("```\n```")
    assert [s.copy for s in segs if s.copy is not None] == [""]


# ---------- never breaks ----------
@pytest.mark.parametrize("value", ["", " ", "\n\n", None, 123, "\x00", "😀 **😀**"])
def test_odd_input_never_raises(value):
    assert isinstance(render_markdown(value), list)
    assert isinstance(plain_text(value), str)


def test_plain_text_is_unchanged():
    text = "Just a normal sentence, with commas. And (brackets) - and a dash."
    assert styled(text) == [(text, ())]


def test_huge_messages_are_left_as_plain_text():
    big = "**x** " * (MAX_CHARS // 4)
    assert render_markdown(big) == [Seg(big)]


def test_random_junk_never_raises():
    rng = random.Random(7)
    pieces = list("*_`~[]()#>-+. \n\\!abc12|:") + ["```", "**", "__", "~~", "\n\n", "1. ", "- ", "> ", "# "]
    for _ in range(3000):
        junk = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 80)))
        for seg in render_markdown(junk):
            assert isinstance(seg.text, str) and isinstance(seg.tags, tuple)
        assert isinstance(plain_text(junk), str)


@pytest.mark.parametrize("text", [
    "_a " * 8000, "~~a " * 6000, "*a " * 3000, "**a " * 3000, "*a**b***c_" * 2000,
    " ".join("`" * k + "a" for k in range(1, 150)), "# " + "a #" * 10000, "*" * 30000,
    "[x](y" * 5000, "- " * 10000 + "x", "```\n" * 5000,
])
def test_pathological_input_stays_fast(text):
    start = time.perf_counter()
    render_markdown(text)
    assert time.perf_counter() - start < 1.5


def test_parse_inline_depth_is_limited():
    deep = "*" * 3 + "x" + "*" * 3
    nested = "**" * 40 + "x" + "**" * 40
    assert isinstance(parse_inline(deep), list)
    assert isinstance(parse_inline(nested), list)