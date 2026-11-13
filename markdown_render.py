"""A small, dependency-free Markdown reader for JUGNU's chat bubbles.

It does not draw anything. It turns Markdown text into a flat list of `Seg`
pieces (text + style tag names) that desktop_app.py inserts into a tk.Text
widget. Keeping it free of Tkinter means it can be unit-tested without a window.

Supported: **bold**, *italic*, ***both***, ~~strike~~, `inline code`,
[links](url), # headings, - / * / + bullets, 1. numbered lists (nested by
indent), > quotes, --- rules and ``` fenced code blocks (the code text is kept
exactly as written). Anything else is shown as ordinary text.

render_markdown() never raises: on any problem it falls back to plain text.
"""
import re
from collections import namedtuple

# text: what to insert.  tags: style names for tk.Text.  copy: when not None, this
# piece is not text at all but a spot for a "Copy" button that copies this code.
Seg = namedtuple("Seg", ["text", "tags", "copy"])
Seg.__new__.__defaults__ = ((), None)

MAX_CHARS = 100_000   # longer messages are shown as plain text
MAX_DEPTH = 6         # how deeply bold/italic may nest
MAX_LIST_LEVEL = 4    # deepest bullet indent that gets its own indentation

_ESCAPABLE = set("\\`*_{}[]()#+-.!~|>")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_RULE_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_BULLET_RE = re.compile(r"^([ \t]*)[-*+][ \t]+(.*)$")
_NUMBER_RE = re.compile(r"^([ \t]*)(\d{1,9})([.)])[ \t]+(.*)$")
_QUOTE_RE = re.compile(r"^ {0,3}>[ \t]?(.*)$")
_LINK_RE = re.compile(r"\[([^\[\]\n]+)\]\(([^()\s]+)\)")


def _add_tag(tags, name):
    """Add a style name. Bold + italic become one 'bolditalic' tag (Tk cannot merge two fonts)."""
    names = set(tags)
    names.add(name)
    if "bold" in names and "italic" in names:
        names -= {"bold", "italic"}
        names.add("bolditalic")
    if "bolditalic" in names:
        names -= {"bold", "italic"}
    return tuple(sorted(names))


def _find_code_close(text, start, run):
    """Index of the next backtick run that is exactly `run` long, or -1."""
    k, n = start, len(text)
    while k < n:
        if text[k] == "`":
            end = k
            while end < n and text[end] == "`":
                end += 1
            if end - k == run:
                return k
            k = end
        else:
            k += 1
    return -1


def _try_emphasis(text, i, tags, depth, dead):
    """Try to read **bold**, *italic*, ***both***, __x__, _x_ or ~~strike~~ at text[i].

    Returns (segments, next_index) or None when the marker is just a literal character.
    `dead` remembers markers that already failed to find any closing partner: a later
    marker of the same kind cannot find one either, so the search is not repeated
    (this keeps strange input such as thousands of lone stars fast).
    """
    ch, n = text[i], len(text)
    if text.startswith("~~", i):
        marker, name = "~~", "strike"
    elif ch in "*_" and text.startswith(ch * 3, i):
        marker, name = ch * 3, "bolditalic"
    elif ch in "*_" and text.startswith(ch * 2, i):
        marker, name = ch * 2, "bold"
    elif ch in "*_":
        marker, name = ch, "italic"
    else:
        return None
    size = len(marker)
    before = text[i - 1] if i else " "
    after = text[i + size] if i + size < n else " "
    # Not emphasis: "2*3*4", "snake_case_name", "x**2 + y**2", "5 * 3", or an empty "** **".
    if ch in "*_" and before.isalnum():
        return None
    if after.isspace():
        return None
    if i >= dead.get(marker, len(text) + 1):
        return None
    j = i + size
    while True:
        j = text.find(marker, j)
        if j == -1:
            dead[marker] = min(i, dead.get(marker, i))
            return None
        prev = text[j - 1]
        following = text[j + size] if j + size < n else " "
        good = j > i + size and not prev.isspace() and prev != "\\"
        if good and ch in "*_":
            good = not following.isalnum()
            if size == 1 and (prev == ch or following == ch):
                good = False  # part of a longer ** run, so not the closing marker
        if good:
            break
        j += 1
    inner = parse_inline(text[i + size:j], _add_tag(tags, name), depth + 1)
    return inner, j + size


def parse_inline(text, tags=(), depth=0):
    """Turn one line of Markdown into Segs. `tags` are style names applied to everything."""
    segs, buf, i, n = [], [], 0, len(text)
    dead = {}  # markers and backtick runs that have no closing partner in this text

    def flush():
        if buf:
            segs.append(Seg("".join(buf), tags))
            buf.clear()

    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in _ESCAPABLE:
            buf.append(text[i + 1])  # "\*" shows a plain star
            i += 2
        elif ch == "`":
            end = i
            while end < n and text[end] == "`":
                end += 1
            run = end - i
            close = -1 if ("`", run) in dead and i >= dead[("`", run)] else _find_code_close(text, end, run)
            if close == -1:
                dead[("`", run)] = min(i, dead.get(("`", run), i))
                buf.append(text[i:end])  # no closing backticks: show them as they are
                i = end
            else:
                flush()
                code = text[end:close]
                if len(code) > 1 and code[0] == " " and code[-1] == " " and code.strip():
                    code = code[1:-1]
                segs.append(Seg(code, _add_tag(tags, "icode")))
                i = close + run
        elif ch == "[" and (match := _LINK_RE.match(text, i)) and depth < MAX_DEPTH:
            flush()
            label, url = match.group(1), match.group(2)
            segs.extend(parse_inline(label, _add_tag(tags, "link"), depth + 1))
            if label != url:
                segs.append(Seg(f" ({url})", _add_tag(tags, "linkurl")))
            i = match.end()
        elif ch in "*_~" and depth < MAX_DEPTH:
            found = _try_emphasis(text, i, tags, depth, dead)
            if found:
                flush()
                segs.extend(found[0])
                i = found[1]
            else:
                buf.append(ch)
                i += 1
        else:
            buf.append(ch)
            i += 1
    flush()
    return segs


def _merge(segs):
    """Join neighbouring pieces that have the same style, so fewer inserts are needed."""
    merged = []
    for seg in segs:
        if (merged and seg.copy is None and merged[-1].copy is None
                and merged[-1].tags == seg.tags):
            merged[-1] = Seg(merged[-1].text + seg.text, seg.tags)
        else:
            merged.append(seg)
    return merged


def _blocks_to_rows(text):
    """Read Markdown line by line. Returns rows of (segments, tags for the line break)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rows = []

    def blank():
        return ([], ())

    def add_blank():
        if rows and rows[-1] != blank():
            rows.append(blank())

    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1

        fence = _FENCE_RE.match(line)
        if fence and not (fence.group(1)[0] == "`" and "`" in fence.group(2)):
            mark, info = fence.group(1), fence.group(2).strip()
            language = info.split()[0] if info else ""
            closer = re.compile(r"^ {0,3}" + re.escape(mark[0]) + "{%d,}[ \t]*$" % len(mark))
            code_lines = []
            while i < len(lines) and not closer.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip the closing fence (a missing one just ends the block at the end)
            add_blank()
            rows.append(([Seg(" " + (language or "code") + " ", ("codehead",)),
                          Seg("", ("codehead",), "\n".join(code_lines))], ("codehead",)))
            for code_line in code_lines:
                rows.append(([Seg(code_line, ("code",))] if code_line else [], ("code",)))
            rows.append(blank())
            continue

        if not line.strip():
            if rows:
                add_blank()
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = min(len(heading.group(1)), 3)
            rows.append((parse_inline(heading.group(2), ("h%d" % level,)), ()))
            continue

        if _RULE_RE.match(line):
            rows.append(([Seg("─" * 28, ("rule",))], ()))
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            rows.append(([Seg("│ ", ("quote",))] + parse_inline(quote.group(1), ("quote",)), ()))
            continue

        bullet = _BULLET_RE.match(line)
        number = None if bullet else _NUMBER_RE.match(line)
        if bullet or number:
            indent = (bullet or number).group(1).expandtabs(4)
            level = min(len(indent) // 2, MAX_LIST_LEVEL)
            if bullet:
                marker, body = ("•" if level % 2 == 0 else "◦"), bullet.group(2)
            else:
                marker, body = number.group(2) + number.group(3), number.group(4)
            rows.append(([Seg(marker + " ", ("li%d" % level,))]
                         + parse_inline(body, ("li%d" % level,)), ()))
            continue

        rows.append((parse_inline(line), ()))

    while rows and rows[-1] == blank():
        rows.pop()
    return rows


def render_markdown(text):
    """Markdown text -> list of Seg. Never raises; falls back to one plain Seg."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    if len(text) > MAX_CHARS:
        return [Seg(text)]
    try:
        segs = []
        rows = _blocks_to_rows(text)
        for number, (row, newline_tags) in enumerate(rows):
            segs.extend(row)
            if number < len(rows) - 1:
                segs.append(Seg("\n", newline_tags))
        return _merge(segs) or [Seg(text)]
    except Exception:  # a parser bug must never break the chat
        return [Seg(text)]


def plain_text(text):
    """What the message reads like without Markdown symbols (used for read-aloud)."""
    try:
        return "".join(seg.text for seg in render_markdown(text) if seg.copy is None)
    except Exception:
        return text if isinstance(text, str) else ""