# ⏩ Forward Pass — daily tabular-AI newsletter

A daily digest of new papers relevant to tabular foundation models —
delivered every weekday morning, zero servers to maintain.

### 📬 [**Subscribe (web + RSS)**](https://gblayer.github.io/tabular-ml-newsletter/) &nbsp;·&nbsp; [RSS feed](https://gblayer.github.io/tabular-ml-newsletter/rss.xml) &nbsp;·&nbsp; [Read the archive](https://gblayer.github.io/tabular-ml-newsletter/)

Free at any scale — add the RSS feed to your reader; unsubscribe by removing it.

## How it works

```
┌─ Stage 1: CANDIDATE GENERATION (broad, cheap) ──────────────────────┐
│  • arXiv sweep of cs.LG/stat.ML/cs.AI/cs.CL/cs.DB/cs.IR (last 24h)  │
│    → generous keyword prefilter (config.yaml: prefilter_keywords)   │
│  • arXiv author queries for every watchlist author                  │
│  • HuggingFace Daily Papers (all of them)                           │
│  • OpenReview recent-notes search (best-effort)                     │
│  • [optional] Semantic Scholar: new papers citing your seed papers  │
└──────────────────────────────────────────────────────────────────────┘
┌─ Stage 2: RELEVANCE JUDGMENT (Claude Haiku, batched) ───────────────┐
│  Each candidate is scored 0-10 against your TOPIC PROFILE — a rich  │
│  natural-language description of your PhD. This is what makes the   │
│  filter broad: adapters, distillation, TFM efficiency, table        │
│  serialization etc. get caught even with zero keyword overlap.      │
└──────────────────────────────────────────────────────────────────────┘
┌─ Stage 3: DIGEST (Claude Sonnet) ───────────────────────────────────┐
│  Top papers get a pedagogical 3-bullet summary:                     │
│  problem/goal → method → limitations, plus the link.                │
└──────────────────────────────────────────────────────────────────────┘
```

Runs on GitHub Actions cron every morning. Dedup state
(`seen_papers.json`) is committed back to the repo, so overlapping
windows and updated arXiv versions never spam you twice.

## Setup (~10 minutes)

1. **Create a GitHub repo** and push this folder to it.

2. **Add repository secrets** (Settings → Secrets and variables →
   Actions → New repository secret):

   | Secret | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | from console.anthropic.com |
   | `SMTP_USER` | your Gmail address |
   | `SMTP_PASSWORD` | a Gmail **App Password** (myaccount.google.com → Security → 2-Step Verification → App passwords) — *not* your normal password |
   | `NEWSLETTER_TO` | the address that receives the digest (can equal `SMTP_USER`) |
   | `S2_API_KEY` | *(optional)* Semantic Scholar key, only if you enable `semantic_scholar` in config |

   Not on Gmail? Any SMTP provider works — change `smtp_host`/`smtp_port`
   in `config.yaml`.

3. **Send issue #1 (last week's papers):** Actions tab → *Daily Tabular
   ML Newsletter* → Run workflow → tick **first_run** → Run.

   Tip: tick **dry_run** too on your very first attempt — instead of
   emailing, it uploads `preview.html` as a workflow artifact so you can
   check the output and tune `config.yaml` before going live.

4. Done. The cron fires daily at 07:30 UTC (delivered before 10:00 Paris).
   arXiv announces new submissions around midnight UTC Mon–Fri, so the
   morning run catches the fresh batch. Weekends are naturally quiet.

## Tuning

Everything lives in `config.yaml`:

- **`topic_profile`** — the heart of the system. If you start a new
  research thread (e.g. test-time adaptation), add two lines here and
  the filter follows. No code changes.
- **`author_watchlist`** — new papers by these people are candidates
  regardless of keywords.
- **`max_papers_in_newsletter`** — daily cap (default 12).
- **Threshold too loose/strict?** Change `threshold` in
  `newsletter/relevance.py::filter_papers` (default 6/10), or just make
  the NOT-relevant section of the topic profile more explicit.

## Local testing

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python -m newsletter.main --first-run --dry-run   # writes preview.html
open preview.html
```

## Costs

- GitHub Actions: free (public repo) or well within free tier (private).
- Claude API: roughly $0.05–0.30/day depending on candidate volume —
  Haiku scores ~50–200 abstracts in batches, Sonnet writes ≤12 summaries.
- arXiv / HF / OpenReview APIs: free.

## Ideas for later (good Claude Code tasks)

- Weekly "digest of digests" every Monday summarizing the week's themes.
- Google Scholar alerts → Gmail ingestion (Scholar has no API, but you
  can parse its alert emails via the Gmail API as an extra source).
- A `/rate` reply loop: forward feedback to a file that gets appended to
  the topic profile ("more like this / less like this").
- Push top papers into a Zotero collection via the Zotero API.
