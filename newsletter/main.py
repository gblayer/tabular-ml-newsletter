"""Entry point.

    python -m newsletter.main                 # daily window (config: lookback_hours)
    python -m newsletter.main --first-run     # 7-day backfill for issue #1
    python -m newsletter.main --dry-run       # print instead of emailing

Pipeline: fetch candidates (broad) → dedup vs seen → keyword/author tag →
Claude relevance filter (broad topic profile) → Claude 3-bullet summaries →
HTML email → persist seen ids.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import state
from .emailer import build_html, send
from .models import Paper
from .relevance import filter_papers, summarize
from .sources import arxiv_source, hf_daily, openreview_source, semantic_scholar

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("newsletter")

CONFIG = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text())


def keyword_prefilter(papers: list[Paper], keywords: list[str]) -> list[Paper]:
    patterns = [(kw, re.compile(re.escape(kw), re.IGNORECASE)) for kw in keywords]
    kept = []
    for p in papers:
        text = f"{p.title} {p.abstract}"
        for kw, pat in patterns:
            if pat.search(text):
                p.matched_keyword = p.matched_keyword or kw
                kept.append(p)
                break
    return kept


def gather_candidates(since: datetime) -> list[Paper]:
    candidates: dict[str, Paper] = {}

    def add(papers: list[Paper]):
        for p in papers:
            if p.id not in candidates:
                candidates[p.id] = p
            else:  # keep richer match info
                existing = candidates[p.id]
                existing.matched_author = existing.matched_author or p.matched_author
                existing.matched_keyword = existing.matched_keyword or p.matched_keyword

    if CONFIG["arxiv"]["enabled"]:
        broad = arxiv_source.fetch_recent_by_category(
            CONFIG["arxiv"]["categories"], since, CONFIG["arxiv"]["max_results_per_category"]
        )
        add(keyword_prefilter(broad, CONFIG["prefilter_keywords"]))
        add(arxiv_source.fetch_by_authors(CONFIG["author_watchlist"], since))

    if CONFIG["huggingface_daily"]["enabled"]:
        add(hf_daily.fetch(since))

    if CONFIG["openreview"]["enabled"]:
        add(openreview_source.fetch(CONFIG["openreview"]["search_terms"], since))

    if CONFIG["semantic_scholar"]["enabled"]:
        add(semantic_scholar.fetch_new_citers(since))

    return list(candidates.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-run", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Routine mode: dump deduped candidates to candidates.json and exit. "
             "No API key needed — the Claude Code routine session does the "
             "scoring/summaries, then calls newsletter.finalize.",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    until = now  # exclusive upper bound on publication time
    if args.first_run:
        since = now - timedelta(days=CONFIG["run"]["first_run_lookback_days"])
        window_label = f"last {CONFIG['run']['first_run_lookback_days']} days"
    elif CONFIG["run"].get("weekly", False):
        # Weekly cadence: the previous FULL calendar week, Monday 00:00 to
        # Sunday 23:59 (Europe/Paris). Anything announced after the week
        # ended is excluded here AND left unseen, so it rolls into next week.
        paris = ZoneInfo("Europe/Paris")
        now_paris = now.astimezone(paris)
        week_end_paris = (now_paris - timedelta(days=now_paris.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        week_start_paris = week_end_paris - timedelta(days=7)
        since = week_start_paris.astimezone(timezone.utc)
        until = week_end_paris.astimezone(timezone.utc)
        window_label = (
            f"week of {week_start_paris:%b %d} – "
            f"{(week_end_paris - timedelta(days=1)):%b %d}"
        )
    elif now.weekday() == 0:  # daily-mode Monday: reach back to Friday
        since = now - timedelta(hours=CONFIG["run"].get("monday_lookback_hours", 74))
        window_label = "since Friday"
    else:
        since = now - timedelta(hours=CONFIG["run"]["lookback_hours"])
        window_label = "last 24 hours"
    log.info("Window: %s -> %s", since.isoformat(), until.isoformat())

    seen = state.load_seen()
    candidates = [
        p for p in gather_candidates(since)
        if p.id not in seen and p.published < until
    ]
    log.info("Candidates after dedup: %d", len(candidates))

    if args.fetch_only:
        import dataclasses
        import json

        payload = {
            "window_label": window_label,
            "candidates": [
                {**dataclasses.asdict(p), "published": p.published.isoformat()}
                for p in candidates
            ],
        }
        Path("candidates.json").write_text(json.dumps(payload, indent=1))
        print(f"[fetch-only] wrote candidates.json with {len(candidates)} candidates")
        return 0

    relevant: list[Paper] = []
    if candidates:
        relevant = filter_papers(
            candidates,
            CONFIG["topic_profile"],
            CONFIG["claude"]["filter_model"],
            CONFIG["claude"]["filter_batch_size"],
        )[: CONFIG["claude"]["max_papers_in_newsletter"]]
        for p in relevant:
            summarize(p, CONFIG["claude"]["summary_model"])

    html = build_html(relevant, window_label)
    subject = f"{CONFIG['email']['subject_prefix']} — {now.strftime('%b %d')} ({len(relevant)} papers)"

    if args.dry_run:
        Path("preview.html").write_text(html)
        print(f"[dry-run] {subject}\n[dry-run] wrote preview.html")
    else:
        send(html, subject, CONFIG["email"]["smtp_host"], CONFIG["email"]["smtp_port"])
        log.info("Email sent: %s", subject)

    # Mark everything scored (not just sent) as seen, so rejected papers
    # aren't re-scored tomorrow when windows overlap.
    seen.update(p.id for p in candidates)
    state.save_seen(seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
