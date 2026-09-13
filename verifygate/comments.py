"""Strip comments so a check counts code, not commentary.

A check that asks "is this string still in the file?" is satisfied by a comment
containing the string.  That is not a hypothetical: an implementer asked to
keep some text while restructuring it once parked the deleted fragments in a
block comment headed "source markers for former fragments", and the check went
green across twenty-three files.

So before counting, take the comments out.  This is a scanner, not a parser: it
tracks string literals well enough that a URL inside a quoted string is not
mistaken for a line comment, and it knows which comment syntaxes belong to
which extension.  It does not understand every corner of every grammar, and it
says so - :func:`strip` is documented as approximate, and both the strict and
the loose reading are available so a caller can require agreement.
"""

from __future__ import annotations

import os
from typing import Dict, List, Sequence, Tuple

#: extension -> (line comment markers, block comment pairs, string quote chars)
_LANGS: Dict[str, Tuple[Sequence[str], Sequence[Tuple[str, str]], Sequence[str]]] = {}


def _reg(exts, line, block, quotes):
    for e in exts:
        _LANGS[e] = (tuple(line), tuple(block), tuple(quotes))


_reg([".py", ".pyi"], ["#"], [], ['"""', "'''", '"', "'"])
_reg([".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"], ["//"], [("/*", "*/")], ['"', "'", "`"])
_reg([".java", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".go", ".rs", ".swift", ".kt"],
     ["//"], [("/*", "*/")], ['"', "'"])
_reg([".php"], ["//", "#"], [("/*", "*/"), ("<!--", "-->")], ['"', "'"])
_reg([".css", ".scss", ".less"], [], [("/*", "*/")], ['"', "'"])
_reg([".html", ".htm", ".xml", ".svg", ".vue", ".xhtml"], [], [("<!--", "-->")], ['"', "'"])
_reg([".sh", ".bash", ".zsh", ".rb", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf"],
     ["#"], [], ['"', "'"])
_reg([".sql"], ["--"], [("/*", "*/")], ["'", '"'])
_reg([".ps1", ".psm1"], ["#"], [("<#", "#>")], ['"', "'"])

#: used when the extension is unknown: everything plausible is treated as a comment
_FALLBACK = (("//", "#", "--"), (("/*", "*/"), ("<!--", "-->")), ('"', "'", "`"))


def rules_for(path: str):
    """Comment and string rules for a path. Unknown extensions get a loose set."""
    return _LANGS.get(os.path.splitext(path)[1].lower(), _FALLBACK)


def strip(text: str, path: str = "", keep_strings: bool = True) -> str:
    """Return ``text`` with comments replaced by spaces of the same length.

    Lengths and line breaks are preserved so that line numbers and offsets
    still line up with the original.

    ``keep_strings=False`` also blanks string literals, which is the stricter
    reading: it catches text parked in an unused constant, and it also blanks
    text that is legitimately a user-visible string.  Callers that care about
    the difference should run both and compare.

    This is approximate by construction; see the module docstring.
    """
    line_marks, block_pairs, quotes = rules_for(path)
    # longest first so "///" and '"""' win over their prefixes
    line_marks = tuple(sorted(line_marks, key=len, reverse=True))
    quotes = tuple(sorted(quotes, key=len, reverse=True))
    block_pairs = tuple(block_pairs)

    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        # inside a string literal: copy it out (or blank it) and skip to the end
        q = _starts_with_any(text, i, quotes)
        if q:
            j = _end_of_string(text, i + len(q), q)
            chunk = text[i:j]
            out.append(chunk if keep_strings else _blank(chunk))
            i = j
            continue

        pair = _starts_with_block(text, i, block_pairs)
        if pair:
            open_s, close_s = pair
            end = text.find(close_s, i + len(open_s))
            end = n if end == -1 else end + len(close_s)
            out.append(_blank(text[i:end]))
            i = end
            continue

        m = _starts_with_any(text, i, line_marks)
        if m:
            end = text.find("\n", i)
            end = n if end == -1 else end
            out.append(_blank(text[i:end]))
            i = end
            continue

        out.append(ch)
        i += 1
    return "".join(out)


def _blank(s: str) -> str:
    return "".join("\n" if c == "\n" else " " for c in s)


def _starts_with_any(text: str, i: int, marks: Sequence[str]):
    for m in marks:
        if m and text.startswith(m, i):
            return m
    return None


def _starts_with_block(text: str, i: int, pairs):
    for open_s, close_s in pairs:
        if text.startswith(open_s, i):
            return (open_s, close_s)
    return None


def _end_of_string(text: str, i: int, quote: str) -> int:
    """Index just past the closing quote (or end of text)."""
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if text.startswith(quote, i):
            return i + len(quote)
        # a single-character quote does not survive a newline in most languages
        if len(quote) == 1 and c == "\n" and quote in ("'", '"'):
            return i
        i += 1
    return n


def literals(text: str, path: str = "", min_len: int = 3) -> List[str]:
    """Contents of the string literals in ``text``, outside comments.

    Quoted text is what actually gets parked: a label is lifted out of the code
    and dropped into a comment so that a "the wording is still there" check
    stays green.  Comparing literals before and after catches that even when
    the surrounding line was rewritten.
    """
    code = strip(text, path)
    _, _, quotes = rules_for(path)
    quotes = tuple(sorted(quotes, key=len, reverse=True))
    out: List[str] = []
    i, n = 0, len(code)
    while i < n:
        q = _starts_with_any(code, i, quotes)
        if not q:
            i += 1
            continue
        j = _end_of_string(code, i + len(q), q)
        body = code[i + len(q): max(i + len(q), j - len(q))]
        if len(body.strip()) >= min_len:
            out.append(body)
        i = j
    return out


def count_in_code(text: str, needle: str, path: str = "") -> int:
    """How many times ``needle`` appears outside comments."""
    if not needle:
        return 0
    return strip(text, path).count(needle)


def count_in_comments(text: str, needle: str, path: str = "") -> int:
    """How many times ``needle`` appears *only* inside comments."""
    if not needle:
        return 0
    return text.count(needle) - count_in_code(text, needle, path)
