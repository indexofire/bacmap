"""Safe Markdown renderer for generated research reports."""

from __future__ import annotations

from bacmap.interfaces.web.markdown import render_markdown


def test_headings_lists_tables_and_inline():
    text = (
        "# Title\n\n"
        "A **bold** and *italic* with `code` and [link](https://example.org).\n\n"
        "- one\n- two\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n"
    )
    html = render_markdown(text)
    assert "<h1>Title</h1>" in html
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert "<code>code</code>" in html
    assert '<a href="https://example.org"' in html
    assert "<ul><li>one</li><li>two</li></ul>" in html
    assert "<table>" in html and "<th>A</th>" in html and "<td>1</td>" in html


def test_raw_html_is_escaped():
    html = render_markdown("<script>alert(1)</script>\n")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_javascript_links_are_removed():
    html = render_markdown("[click](javascript:alert(1))")
    assert "javascript:" not in html
    assert "click" in html


def test_fenced_code_is_escaped():
    html = render_markdown("```\n<script>x</script>\n```\n")
    assert "<pre><code>" in html
    assert "&lt;script&gt;" in html


def test_protocol_relative_links_are_removed():
    """“//evil.com”是协议相对外链——站内 "/" 前缀不能放行它（零外联）。"""
    html = render_markdown("[click](//evil.example.com/x)")
    assert "evil.example.com" not in html
    assert "click" in html


def test_relative_links_still_allowed():
    html = render_markdown("[inner](/research/sessions)")
    assert '<a href="/research/sessions"' in html
