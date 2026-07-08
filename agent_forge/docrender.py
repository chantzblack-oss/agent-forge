"""Render lesson/dive markdown into a typeset PDF.

Raw .md files display as unformatted plain text in Telegram — machine
format, not a deliverable. This renders them into a designed PDF (real
typography, styled code blocks, tables, clickable links, inline SVG)
using the Chromium that's already on the host for video stills.
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

_CSS = """
 @page { margin: 0; }
 * { box-sizing: border-box; }
 body { margin: 0; font: 15px/1.65 -apple-system, 'Segoe UI', Roboto,
        Helvetica, Arial, sans-serif; color: #1d3038; background: #ffffff; }
 .page { padding: 56px 60px; max-width: 820px; margin: 0 auto; }
 .band { height: 10px; background: linear-gradient(90deg,#ff7a5e,#35c2d6); }
 h1 { font-size: 33px; line-height: 1.15; letter-spacing: -.02em;
      margin: 18px 0 6px; color: #0e2731; }
 .sub { color: #6b8893; font-size: 13px; margin-bottom: 26px;
        text-transform: uppercase; letter-spacing: .12em; font-weight: 700; }
 h2 { font-size: 21px; margin: 38px 0 12px; color: #0e2731;
      padding-bottom: 7px; border-bottom: 2px solid #ffd9cf; }
 h2::before { content: '◆ '; color: #ff7a5e; font-size: 14px;
      vertical-align: 2px; }
 h3 { font-size: 16px; margin: 22px 0 6px; color: #0e2731; }
 p { margin: 8px 0; }
 li { margin: 5px 0; }
 ul, ol { padding-left: 24px; }
 strong { color: #0e2731; }
 a { color: #0e8ea3; text-decoration: none; border-bottom: 1px solid #9fd8e0; }
 code { background: #f0f5f6; border: 1px solid #dde8ea; border-radius: 5px;
        padding: 1px 6px; font: 13px/1.5 ui-monospace, Menlo, Consolas,
        monospace; color: #b03d2e; }
 pre { background: #0e2731; color: #d9ebee; border-radius: 10px;
       padding: 14px 18px; overflow-x: hidden; white-space: pre-wrap;
       word-break: break-word; page-break-inside: avoid; }
 pre code { background: none; border: none; color: inherit; padding: 0; }
 blockquote { border-left: 4px solid #35c2d6; margin: 16px 0;
              padding: 10px 18px; color: #23444f; background: #f2f9fa;
              border-radius: 0 10px 10px 0; font-size: 16px;
              page-break-inside: avoid; }
 blockquote p { margin: 4px 0; }
 table { border-collapse: collapse; width: 100%; margin: 16px 0;
         font-size: 14px; page-break-inside: avoid; }
 th, td { border: 1px solid #dde8ea; padding: 8px 12px; text-align: left; }
 th { background: #0e2731; color: #eaf3f2; letter-spacing: .02em; }
 tr:nth-child(even) td { background: #f6fafb; }
 svg { max-width: 100%; height: auto; display: block; margin: 18px auto;
       page-break-inside: avoid; }
 h2, h3 { page-break-after: avoid; }
"""


def _md_to_html(md: str) -> str:
    """Markdown -> HTML. Uses python-markdown when available; falls back to
    a small built-in converter good enough for our lesson structure."""
    try:
        import markdown  # type: ignore
        return markdown.markdown(
            md, extensions=["fenced_code", "tables", "sane_lists"])
    except ImportError:
        return _mini_md(md)


def _mini_md(md: str) -> str:
    out: list[str] = []
    in_code = False
    in_list = False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
            else:
                out.append("<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(_html.escape(line))
            continue
        stripped = line.strip()
        if stripped.startswith("<svg"):
            out.append(line)          # inline diagrams pass through raw
            continue
        if stripped.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(stripped[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(m.group(2))}</h{n}>")
        elif stripped:
            out.append(f"<p>{_inline(stripped)}</p>")
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


def _inline(text: str) -> str:
    text = _html.escape(text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def md_to_pdf(md_path: str | Path, subtitle: str = "Agent Forge lesson") -> Path:
    """Render a markdown doc to a typeset PDF next to it. Returns the path."""
    md_path = Path(md_path)
    md = md_path.read_text(encoding="utf-8")
    md = re.sub(r"^<!--.*?-->\s*", "", md, flags=re.DOTALL)
    body = _md_to_html(md)
    page = (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<style>{_CSS}</style></head><body>"
            f"<div class='band'></div><div class='page'>"
            f"<div class='sub'>{_html.escape(subtitle)}</div>"
            f"{body}</div></body></html>")

    import tempfile
    from playwright.sync_api import sync_playwright
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as f:
        f.write(page)
        html_path = f.name

    pdf_path = md_path.with_suffix(".pdf")
    with sync_playwright() as p:
        import os
        exe = "/opt/pw-browsers/chromium"
        b = p.chromium.launch(
            executable_path=exe if os.path.exists(exe) else None,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--renderer-process-limit=1", "--no-zygote",
                  "--single-process"])
        pg = b.new_page()
        pg.goto("file://" + html_path)
        pg.pdf(path=str(pdf_path), format="A4", print_background=True)
        b.close()
    return pdf_path
