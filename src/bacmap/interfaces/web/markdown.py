"""Small, safe Markdown renderer for generated research reports.

Only the subset bacmap emits is supported: headings, paragraphs, lists, fenced code,
pipe tables, bold/italic, inline code and links. Raw HTML is always escaped; link
schemes are restricted to http(s), mailto and relative paths.
"""

from __future__ import annotations

import html
import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_ORDERED = re.compile(r"^\s*\d+\.\s+(.*)$")
_UNORDERED = re.compile(r"^\s*[-*+]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def _safe_url(raw: str) -> str | None:
    url = html.unescape(raw.strip())
    if url.startswith(("http://", "https://", "mailto:", "#")):
        return html.escape(url, quote=True)
    # "/" 允许站内相对链接，但 "//evil.com" 是协议相对外链（违反零外联）
    if url.startswith("/") and not url.startswith("//"):
        return html.escape(url, quote=True)
    return None


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", escaped)
    escaped = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", escaped)
    escaped = _ITALIC.sub(lambda m: f"<em>{m.group(1)}</em>", escaped)

    def link(match: re.Match[str]) -> str:
        label = match.group(1)
        url = _safe_url(match.group(2))
        if url is None:
            return label
        return f'<a href="{url}" rel="noreferrer noopener">{label}</a>'

    return _LINK.sub(link, escaped)


def _table(lines: list[str], start: int) -> tuple[str, int] | None:
    if start + 1 >= len(lines) or "|" not in lines[start]:
        return None
    if not _TABLE_SEP.match(lines[start + 1]):
        return None
    header = [cell.strip() for cell in lines[start].strip().strip("|").split("|")]
    rows: list[list[str]] = []
    index = start + 2
    while index < len(lines) and "|" in lines[index] and lines[index].strip():
        rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
        index += 1
    out = ["<table>", "<thead><tr>"]
    out += [f"<th>{_inline(cell)}</th>" for cell in header]
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out), index


def _fenced_code(lines: list[str], start: int) -> tuple[str, int]:
    index = start + 1
    code: list[str] = []
    while index < len(lines) and not lines[index].strip().startswith("```"):
        code.append(lines[index])
        index += 1
    return "<pre><code>" + html.escape("\n".join(code), quote=False) + "</code></pre>", index + 1


def _list(lines: list[str], start: int) -> tuple[str, int]:
    ordered = bool(_ORDERED.match(lines[start]))
    pattern = _ORDERED if ordered else _UNORDERED
    items: list[str] = []
    index = start
    while index < len(lines):
        match = pattern.match(lines[index])
        if match is None:
            break
        items.append(f"<li>{_inline(match.group(1))}</li>")
        index += 1
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(items) + f"</{tag}>", index


def _blockquote(lines: list[str], start: int) -> tuple[str, int]:
    quote: list[str] = []
    index = start
    while index < len(lines) and lines[index].lstrip().startswith(">"):
        quote.append(lines[index].lstrip()[1:].lstrip())
        index += 1
    return f"<blockquote><p>{_inline(' '.join(quote))}</p></blockquote>", index


def _paragraph(lines: list[str], start: int) -> tuple[str, int]:
    paragraph: list[str] = []
    index = start
    while index < len(lines) and lines[index].strip():
        line = lines[index]
        if (
            _HEADING.match(line)
            or line.strip().startswith("```")
            or _ORDERED.match(line)
            or _UNORDERED.match(line)
            or _table(lines, index) is not None
        ):
            break
        paragraph.append(line.strip())
        index += 1
    return f"<p>{_inline(' '.join(paragraph))}</p>", index


def render_markdown(text: str) -> str:
    """Render a safe HTML subset; never emits raw input HTML."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
        elif line.strip().startswith("```"):
            rendered, index = _fenced_code(lines, index)
            out.append(rendered)
        elif _HEADING.match(line):
            heading = _HEADING.match(line)
            if heading is not None:
                level = len(heading.group(1))
                out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            index += 1
        elif line.strip() in {"---", "***", "___"}:
            out.append("<hr>")
            index += 1
        elif _table(lines, index) is not None:
            table = _table(lines, index)
            if table is not None:
                rendered, index = table
                out.append(rendered)
            else:
                index += 1
        elif _ORDERED.match(line) or _UNORDERED.match(line):
            rendered, index = _list(lines, index)
            out.append(rendered)
        elif line.lstrip().startswith(">"):
            rendered, index = _blockquote(lines, index)
            out.append(rendered)
        else:
            rendered, index = _paragraph(lines, index)
            out.append(rendered)
    return "\n".join(out)
