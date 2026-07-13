"""Publish each issue to docs/ for a free, unlimited-scale web + RSS feed.

GitHub Pages (or any static host) serves docs/. Readers subscribe by adding
the RSS feed to a reader or bookmarking the archive — there is no subscriber
list to manage, no unsubscribe logic to build, and no per-reader cost, so
this scales to any audience for free.

Outputs (all under docs/, committed to the repo like seen_papers.json):
  docs/issues/issue-<N>.html   one standalone web page per issue
  docs/index.html              archive + subscribe box (RSS + Feedly)
  docs/rss.xml                 RSS 2.0 feed of all issues
  docs/issues_index.json       manifest (state) driving the archive + feed
  docs/.nojekyll               serve files as-is

Called by finalize.py after a successful (non-dry-run) send.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from . import emailer
from .emailer import ACCENT, ACCENT2, DESK, INK, MONO, MUTED, PAPER, SANS, build_html
from .models import Paper

DOCS = Path("docs")
ISSUES_DIR = DOCS / "issues"
MANIFEST = DOCS / "issues_index.json"


def _nav_html(base_url: str) -> str:
    b = base_url.rstrip("/")
    return (
        f'<div style="max-width:640px;margin:0 auto 14px;font-family:{MONO};font-size:12px;'
        f'letter-spacing:.04em;overflow:hidden;">'
        f'<a href="{b}/" style="color:{ACCENT};text-decoration:none;">&laquo; All issues</a>'
        f'<a href="{b}/rss.xml" style="color:{ACCENT2};text-decoration:none;float:right;">Subscribe (RSS)</a>'
        f'</div>'
    )


def _summary(papers: list[Paper], industry: list[dict], spotlight: dict | None) -> str:
    parts = []
    if papers:
        parts.append(f"{len(papers)} paper" + ("s" if len(papers) != 1 else ""))
    if industry:
        parts.append(f"{len(industry)} industry update" + ("s" if len(industry) != 1 else ""))
    line = ", ".join(parts) if parts else "New issue"
    academia = [str(x).strip() for x in ((spotlight or {}).get("academia") or []) if str(x).strip()]
    if academia:
        line += " — " + academia[0]
    return line


def _rss_xml(items: list[dict], base_url: str, title: str, subtitle: str) -> str:
    b = base_url.rstrip("/")
    entries = []
    for it in items:
        try:
            pub = datetime.fromisoformat(it["iso"]).strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:  # noqa: BLE001
            pub = ""
        link = f"{b}/{it['path']}"
        entries.append(
            "<item>"
            f"<title>{escape(it['title'])}</title>"
            f"<link>{escape(link)}</link>"
            f'<guid isPermaLink="true">{escape(link)}</guid>'
            f"<pubDate>{pub}</pubDate>"
            f"<description>{escape(it.get('summary', ''))}</description>"
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
        f"<title>{escape(title)}</title>"
        f"<link>{escape(b)}/</link>"
        f"<description>{escape(subtitle)}</description>"
        f'<atom:link href="{escape(b)}/rss.xml" rel="self" type="application/rss+xml"/>'
        f"{''.join(entries)}"
        "</channel></rss>\n"
    )


def _index_html(items: list[dict], base_url: str, title: str, subtitle: str) -> str:
    b = base_url.rstrip("/")
    feed = f"{b}/rss.xml"
    feedly = f"https://feedly.com/i/subscription/feed/{feed}"
    rows = []
    for it in items:
        rows.append(
            f'<a href="{b}/{it["path"]}" style="display:block;text-decoration:none;'
            f'border-top:1px solid #d9d7cc;padding:16px 0;">'
            f'<span style="font-family:{MONO};font-size:12px;color:{ACCENT};">Issue {it["number"]:02d}</span>'
            f'<span style="font-family:{MONO};font-size:12px;color:{MUTED};margin-left:12px;">{escape(it["date"])}</span>'
            f'<div style="font-family:{SANS};font-size:15px;color:{INK};margin-top:4px;">{escape(it.get("summary",""))}</div>'
            f'</a>'
        )
    archive = "".join(rows) or (
        f'<p style="font-family:{SANS};color:{MUTED};">No issues published yet.</p>'
    )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title>"
        f'<link rel="alternate" type="application/rss+xml" title="{escape(title)}" href="{escape(feed)}">'
        '<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700'
        '&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" '
        'rel="stylesheet">'
        '<style>body{margin:0;padding:0;}a:hover{opacity:.75;}</style></head>'
        f'<body style="margin:0;padding:32px 12px;background:{DESK};">'
        f'<div style="max-width:640px;margin:0 auto;background:{PAPER};border:1.5px solid {INK};">'
        f'<div style="background:{INK};color:{PAPER};padding:26px 40px 30px;">'
        f'<div style="font-family:{MONO};font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;'
        f'color:#8f8c80;">Daily &middot; Tabular AI</div>'
        f'<h1 style="margin:14px 0 0;font-family:\'Space Grotesk\',\'Helvetica Neue\',Arial,sans-serif;'
        f'font-weight:700;font-size:40px;letter-spacing:-.025em;line-height:.98;text-transform:uppercase;'
        f'color:{PAPER};"><span style="color:{ACCENT};">&raquo;</span>Forward '
        f'<span style="color:{PAPER};">Pass<span style="color:{ACCENT2};">.</span></span></h1>'
        f'<p style="margin:14px 0 0;font-family:{SANS};font-size:13px;color:#c3c0b4;">{escape(subtitle)}</p>'
        f'</div>'
        f'<div style="padding:30px 40px 40px;">'
        # subscribe box
        f'<div style="border:1.5px solid {ACCENT};background:rgba(59,56,245,0.06);padding:18px 20px;margin-bottom:34px;">'
        f'<div style="font-family:{MONO};font-size:11px;font-weight:600;letter-spacing:.1em;'
        f'text-transform:uppercase;color:{ACCENT};margin-bottom:8px;">Subscribe &middot; free</div>'
        f'<div style="font-family:{SANS};font-size:14px;color:{INK};line-height:1.5;">'
        f'Add the feed to your reader &mdash; unsubscribe anytime by removing it.</div>'
        f'<div style="margin-top:10px;font-family:{MONO};font-size:12.5px;color:{INK};word-break:break-all;">'
        f'<a href="{escape(feed)}" style="color:{ACCENT};">{escape(feed)}</a></div>'
        f'<div style="margin-top:12px;"><a href="{escape(feedly)}" '
        f'style="display:inline-block;background:{ACCENT};color:#fff;font-family:{MONO};font-size:12px;'
        f'font-weight:600;letter-spacing:.05em;text-transform:uppercase;padding:8px 14px;">Subscribe on Feedly</a></div>'
        f'</div>'
        # archive
        f'<div style="font-family:{MONO};font-size:11.5px;font-weight:600;letter-spacing:.16em;'
        f'text-transform:uppercase;color:{INK};border-bottom:2px solid {INK};padding-bottom:9px;">Archive</div>'
        f'{archive}'
        f'</div></div></body></html>'
    )


def publish(papers: list[Paper], window_label: str, industry: list[dict],
            spotlight: dict | None, config: dict) -> str:
    """Write the web issue, refresh the archive + RSS feed. Returns the issue URL."""
    site = config.get("site", {})
    base_url = (site.get("base_url") or "").rstrip("/")
    name = config["email"].get("newsletter_name", "Forward Pass")
    subtitle = "Your daily digest of the top papers in tabular AI."

    now = datetime.now()
    issue_no = emailer._issue_number(now)

    ISSUES_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS / ".nojekyll").write_text("")

    # Standalone web page for this issue (same design + a small nav bar).
    issue_html = build_html(
        papers, window_label, industry=industry, spotlight=spotlight, name=name,
        extra_top_html=_nav_html(base_url),
    )
    rel_path = f"issues/issue-{issue_no}.html"
    (DOCS / rel_path).write_text(issue_html)

    # Manifest of all issues (state that drives the archive + feed).
    items = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
    items = [it for it in items if it.get("number") != issue_no]  # idempotent re-run
    items.append({
        "number": issue_no,
        "date": now.strftime("%Y-%m-%d"),
        "iso": now.replace(tzinfo=timezone.utc).isoformat(),
        "title": f"{name} — Issue {issue_no} ({now.strftime('%b %d, %Y')})",
        "path": rel_path,
        "summary": _summary(papers, industry, spotlight),
    })
    items.sort(key=lambda x: x["number"], reverse=True)
    MANIFEST.write_text(json.dumps(items, indent=1))

    (DOCS / "index.html").write_text(_index_html(items, base_url, name, subtitle))
    (DOCS / "rss.xml").write_text(_rss_xml(items, base_url, name, subtitle))

    return f"{base_url}/{rel_path}"
