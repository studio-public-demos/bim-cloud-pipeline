"""Build a browsable HTML documentation hub from the Markdown docs.

Run:  python scripts/build_docs.py
Output: docs/*.html  (open docs/index.html)
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"

PAGES = [
    ("index.html", "Overview", "README.md"),
    ("usage.html", "Usage guide", "USAGE.md"),
    ("architecture.html", "Architecture", "docs/ARCHITECTURE.md"),
    ("brief.html", "Product brief", "PRODUCT_BRIEF.md"),
    ("criteria.html", "Acceptance criteria", "ACCEPTANCE_CRITERIA.md"),
]

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — BIM Cloud Pipeline</title>
<style>
:root {{ --bg:#0b0f17; --panel:#131a26; --border:#263349; --text:#e6edf7;
  --muted:#8b98ad; --accent:#3b82f6; --accent2:#22d3ee; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; line-height:1.6; }}
.layout {{ display:grid; grid-template-columns:260px 1fr; min-height:100vh; }}
.sidebar {{ background:var(--panel); border-right:1px solid var(--border);
  padding:20px 14px; position:sticky; top:0; height:100vh; overflow:auto; }}
.sidebar .logo {{ font-weight:700; font-size:15px; margin-bottom:4px; }}
.sidebar .logo em {{ color:var(--accent2); font-style:normal; }}
.sidebar .sub {{ color:var(--muted); font-size:12px; margin-bottom:18px; }}
.nav a {{ display:block; color:var(--text); text-decoration:none; padding:9px 12px;
  border-radius:8px; font-size:13.5px; margin-bottom:3px; min-height:38px; }}
.nav a:hover {{ background:var(--panel); }}
.nav a.active {{ background:linear-gradient(135deg,var(--accent),#2563eb); color:#fff; }}
.content {{ max-width:860px; padding:32px 40px 80px; }}
.content h1 {{ font-size:26px; margin-top:0; }}
.content h2 {{ font-size:20px; margin-top:32px; border-bottom:1px solid var(--border); padding-bottom:6px; }}
.content h3 {{ font-size:16px; margin-top:24px; }}
.content code {{ background:var(--panel); padding:2px 6px; border-radius:5px;
  font-size:13px; color:var(--accent2); font-family:ui-monospace,Consolas,monospace; }}
.content pre {{ background:#0a0e15; border:1px solid var(--border); border-radius:10px;
  padding:14px 16px; overflow:auto; }}
.content pre code {{ background:none; color:#c7d2e0; padding:0; }}
.content table {{ border-collapse:collapse; width:100%; margin:14px 0; font-size:13.5px; }}
.content th,.content td {{ border:1px solid var(--border); padding:8px 11px; text-align:left; }}
.content th {{ background:var(--panel); }}
.content a {{ color:var(--accent); }}
.content blockquote {{ border-left:3px solid var(--accent); margin:14px 0; padding:4px 16px; color:var(--muted); }}
.content img, .mermaid svg {{ max-width:100%; height:auto; }}
.mermaid {{ background:#0e1522; border:1px solid var(--border); border-radius:10px;
  padding:16px; margin:16px 0; overflow:auto; }}
@media (max-width:820px) {{
  .layout {{ grid-template-columns:1fr; }}
  .sidebar {{ position:static; height:auto; border-right:none; border-bottom:1px solid var(--border); }}
  .content {{ padding:20px 18px 60px; }}
}}
</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <div class="logo">BIM Cloud <em>Pipeline</em></div>
    <div class="sub">Revit & IFC → GLB/GLTF + metadata</div>
    <nav class="nav">
      {nav}
    </nav>
  </aside>
  <main class="content">{body}</main>
</div>
<script>
  mermaid.initialize({{ startOnLoad:false, theme:'dark', securityLevel:'loose' }});
  document.querySelectorAll('pre code.language-mermaid').forEach(function(b){{
    var pre = b.parentElement;
    var div = document.createElement('div');
    div.className = 'mermaid';
    div.textContent = b.textContent;
    pre.replaceWith(div);
  }});
  mermaid.run({{ querySelector: '.mermaid' }});
</script>
</body>
</html>
"""


def render_md(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return markdown.markdown(
        text,
        extensions=["fenced_code", "tables", "sane_lists", "toc"],
        output_format="html5",
    )


def build_nav(active: str) -> str:
    links = []
    for filename, title, _src in PAGES:
        cls = ' class="active"' if filename == active else ""
        links.append(f'<a href="{filename}"{cls}>{title}</a>')
    return "\n      ".join(links)


def main():
    DOCS_DIR.mkdir(exist_ok=True)
    for filename, title, src_rel in PAGES:
        src = ROOT / src_rel
        if not src.exists():
            print(f"skip (missing): {src_rel}")
            continue
        body = render_md(src)
        page = TEMPLATE.format(
            title=html.escape(title),
            nav=build_nav(filename),
            body=body,
        )
        (DOCS_DIR / filename).write_text(page, encoding="utf-8")
        print(f"wrote docs/{filename}  ({len(page):,} bytes)")


if __name__ == "__main__":
    main()
