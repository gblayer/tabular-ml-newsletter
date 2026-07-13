"""Routine-mode finalizer.

Usage:  python -m newsletter.finalize digest.json [--dry-run]

`digest.json` is written BY the Claude Code routine session after it has
read candidates.json and done the scoring/summarizing itself (no API key
needed). Expected shape:

{
  "window_label": "last 24 hours",
  "papers": [
    {
      "id": "arxiv:2606.30336",
      "title": "...", "authors": ["..."], "url": "https://arxiv.org/abs/...",
      "source": "arxiv", "relevance_score": 8,
      "matched_author": null, "matched_keyword": "tabular",
      "is_new_version": false,
      "bullets": {"problem": "...", "method": "...", "results": "...", "limitations": "..."}
    }
  ],
  "industry": [                         # optional; omit or [] if no fresh news
    {"company": "Prior Labs", "headline": "...", "date": "2026-07-07",
     "url": "https://...", "summary": "1-2 sentences, what and why it matters"}
  ],
  "spotlight": {                        # optional; omit if not written
    "theme": "time-series & forecasting",
    "body": "A few sentences on the current status of tabular FMs in this vertical."
  }
}

This script builds the HTML email, sends it via SMTP, and marks ALL
candidates from candidates.json (not just the kept papers) as seen.
The `industry` and `spotlight` blocks are rendered as separate sections;
`seen_papers.json` bookkeeping concerns academic candidates only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import state
from .emailer import build_html, send
from .models import Paper

CONFIG = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text())


def _to_paper(d: dict) -> Paper:
    return Paper(
        id=d["id"],
        title=d.get("title", ""),
        abstract=d.get("abstract", ""),
        authors=d.get("authors", []),
        url=d.get("url", ""),
        published=datetime.now(timezone.utc),
        source=d.get("source", "arxiv"),
        matched_author=d.get("matched_author"),
        matched_keyword=d.get("matched_keyword"),
        is_new_version=bool(d.get("is_new_version", False)),
        relevance_score=int(d.get("relevance_score", 0)),
        bullets=d.get("bullets") or {},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("digest", help="Path to digest.json written by the routine session")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    digest = json.loads(Path(args.digest).read_text())
    papers = sorted(
        (_to_paper(d) for d in digest.get("papers", [])),
        key=lambda p: p.relevance_score,
        reverse=True,
    )[: CONFIG["claude"]["max_papers_in_newsletter"]]
    window_label = digest.get("window_label", "last 24 hours")
    industry = digest.get("industry") or []
    spotlight = digest.get("spotlight") or None
    name = CONFIG["email"].get("newsletter_name", "In-Context")

    # Daily-digest rule: only send when there is something new in the last 24h.
    # A fully quiet day (no papers AND no industry) sends nothing — the email
    # still renders "quiet day" for papers or "no industry updates" for either
    # section when the OTHER has content. Seen-tracking runs regardless.
    has_content = bool(papers) or bool(industry)
    now = datetime.now(timezone.utc)
    send_weekdays = CONFIG["run"].get("send_weekdays", [0, 1, 2, 3, 4])
    day_ok = now.weekday() in send_weekdays

    if has_content and day_ok:
        site_cfg = CONFIG.get("site", {})
        site_url = site_cfg.get("base_url", "") if site_cfg.get("enabled") else ""
        html = build_html(
            papers, window_label, industry=industry, spotlight=spotlight, name=name,
            site_url=site_url,
        )
        extra = f" + {len(industry)} industry" if industry else ""
        subject = (
            f"{CONFIG['email']['subject_prefix']} — {now.strftime('%b %d')} "
            f"({len(papers)} papers{extra})"
        )
        if args.dry_run:
            Path("preview.html").write_text(html)
            print(f"[dry-run] {subject}\n[dry-run] wrote preview.html")
        else:
            send(html, subject, CONFIG["email"]["smtp_host"], CONFIG["email"]["smtp_port"])
            print(f"Email sent: {subject}")
            # Publish the free web issue + RSS feed alongside the email.
            if CONFIG.get("site", {}).get("enabled"):
                from . import publish as _publish
                url = _publish.publish(papers, window_label, industry, spotlight, CONFIG)
                print(f"Published web issue: {url} (docs/ updated)")
    elif not day_ok:
        print(f"{now.strftime('%A')} is not a configured send day "
              f"(run.send_weekdays = {send_weekdays}) — no email sent.")
    else:
        print("Quiet day: no papers and no industry news in the last 24h — no email sent.")

    # Mark every fetched candidate as seen so nothing is re-triaged tomorrow.
    seen = state.load_seen()
    cand_file = Path("candidates.json")
    if cand_file.exists():
        cands = json.loads(cand_file.read_text()).get("candidates", [])
        seen.update(c["id"] for c in cands)
    seen.update(p.id for p in papers)
    state.save_seen(seen)
    print(f"seen_papers.json updated ({len(seen)} ids)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
