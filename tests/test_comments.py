from verifygate import comments


def test_line_comment_is_removed_but_offsets_survive():
    src = "a = 1  // keep me\nb = 2\n"
    out = comments.strip(src, "x.js")
    assert len(out) == len(src)
    assert out.count("\n") == src.count("\n")
    assert "keep me" not in out
    assert "a = 1" in out and "b = 2" in out


def test_url_in_a_string_is_not_a_comment():
    src = 'const u = "https://example.com/a";\nconst v = 2;\n'
    out = comments.strip(src, "x.js")
    assert "example.com" in out
    assert "const v = 2" in out


def test_block_comment_across_lines():
    src = "x\n/* gone\n   also gone */\ny\n"
    out = comments.strip(src, "x.c")
    assert "gone" not in out
    assert "x" in out and "y" in out


def test_hash_comment_in_python_but_not_in_a_string():
    src = 'a = "# not a comment"  # a comment\n'
    out = comments.strip(src, "x.py")
    assert "# not a comment" in out
    assert "a comment" not in out.replace("# not a comment", "")


def test_css_has_no_line_comments():
    src = "a { color: red } // not a comment in css\n"
    out = comments.strip(src, "x.css")
    assert "not a comment in css" in out


def test_html_comment():
    src = "<p>keep</p><!-- drop --><p>keep2</p>"
    out = comments.strip(src, "x.html")
    assert "drop" not in out
    assert "keep" in out and "keep2" in out


def test_count_in_code_and_in_comments_split():
    src = 'greet("hello")\n// hello\n'
    assert comments.count_in_code(src, "hello", "x.js") == 1
    assert comments.count_in_comments(src, "hello", "x.js") == 1


def test_the_actual_stash_pattern():
    """Text deleted from code, parked in a block comment, is seen as such."""
    after = (
        'function f() { return t("x"); }\n'
        "/* source markers for former fragments: 使い方を見る, 保存する */\n"
    )
    assert comments.count_in_code(after, "使い方を見る", "x.js") == 0
    assert comments.count_in_comments(after, "使い方を見る", "x.js") == 1


def test_unknown_extension_uses_the_loose_reading():
    src = "value # trailing\n"
    assert "trailing" not in comments.strip(src, "x.unknownext")


def test_keep_strings_false_blanks_literals():
    src = 'const s = "parked text";\n'
    assert "parked text" not in comments.strip(src, "x.js", keep_strings=False)
    assert "parked text" in comments.strip(src, "x.js", keep_strings=True)


def test_unterminated_comment_does_not_hang_or_leak():
    src = "code\n/* never closed\n"
    out = comments.strip(src, "x.c")
    assert "never closed" not in out
    assert len(out) == len(src)


def test_escaped_quote_inside_string():
    src = 'a = "he said \\"hi\\" // not a comment";\nb = 1\n'
    out = comments.strip(src, "x.js")
    assert "not a comment" in out
    assert "b = 1" in out


def test_literals_are_extracted_from_code_only():
    src = 'var a = "keep me";\n// var b = "in a comment";\n'
    lits = comments.literals(src, "x.js")
    assert "keep me" in lits
    assert "in a comment" not in lits


def test_literals_ignore_very_short_strings():
    src = 'a("x"); b("a real label");\n'
    lits = comments.literals(src, "x.js")
    assert "a real label" in lits
    assert "x" not in lits
