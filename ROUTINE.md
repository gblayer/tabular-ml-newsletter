# Running this newsletter as a Claude Code Routine (no API key, $0 extra on Max)

In routine mode, the daily Claude Code session does the relevance scoring
and summary writing itself — consuming your subscription usage instead of
API credits. The scripts handle fetching, dedup, and email delivery.

## Setup

1. Push this repo to GitHub (routines clone a repo at each run).
2. Go to **claude.ai/code/routines** → **New routine**.
3. Select this repository.
4. In the routine's **cloud environment**, add environment variables
   (Anthropic API key NOT needed). Pick ONE email transport:
   - **Gmail HTTPS API (use this in cloud routines** — their network proxy
     only allows port 443, so raw SMTP :587 is blocked):
     `SMTP_USER` (the from-address / Gmail account), `GMAIL_CLIENT_ID`,
     `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`. See "Gmail API setup" below.
   - **Resend HTTPS API** (alternative): `RESEND_API_KEY`, optional
     `RESEND_FROM` (needs a Resend-verified sender/domain to reach others).
   - **SMTP** (local runs / GitHub Actions only): `SMTP_USER`,
     `SMTP_PASSWORD` (a Gmail App Password).
   Plus `NEWSLETTER_TO` — comma-separated recipients.
   Network access: set the environment to **Full** (needs arxiv.org,
   huggingface.co, googleapis.com for Gmail, and open web for industry news).
5. Trigger: **schedule**, daily, **07:30 UTC** (delivered before 10:00 Paris;
   the run takes ~10-15 min).
6. Paste the prompt below.
7. First issue: run the routine once manually, temporarily replacing the
   flag in step 1 of the prompt with `--first-run --fetch-only` to backfill
   the last 7 days.

## Routine prompt (paste as-is)

```
You are producing my daily tabular-ML paper newsletter. Work autonomously,
no questions. Steps:

1. Install deps and fetch candidates:
     pip install -r requirements.txt
     python -m newsletter.main --fetch-only
   This writes candidates.json (papers from the last 24h, already deduped
   against seen_papers.json).

2. Read config.yaml and internalize the `topic_profile` — it defines what
   is relevant to my PhD. Then read candidates.json and score EVERY
   candidate 0-10 against that profile. Be generous with adjacent-but-
   connected work (adapters, distillation, TFM/LLM efficiency, table
   serialization, relational FMs, benchmarks critique), strict with papers
   that merely apply off-the-shelf tabular models to a domain problem.
   Treat these as CORE (score 7-9, not borderline):
     - in-context learning IN/FOR tabular foundation models (mechanisms,
       theory, empirical studies of TabPFN/TabICL/prior-fitted networks);
     - work that BUILDS ON TabPFN / TabICL / TabPFN-v2 (extends, fine-tunes,
       distills, benchmarks, or uses them as backbone/head/baseline);
     - neural processes (conditional / attentive / transformer NPs) used for
       in-context or probabilistic tabular prediction.

3. For every paper scoring >= 6, write a pedagogical digest with FOUR
   fields — problem (1-2 sentences: goal and why it matters), method (1-2
   sentences, name the core idea concretely), results (1-2 sentences: the
   main empirical/quantitative finding — key numbers, what beat what;
   prefix "Likely:" if inferred), limitations (honest; prefix "Likely:" if
   inferred rather than stated in the abstract). Plain language, no hype,
   max ~40 words per field. Publish ALL papers that score >= 6 even if
   there are fewer than 10; only cap at the 10 highest if more. I know the
   field (TabPFN, tabular ICL, LLM embeddings, relational FMs, neural
   processes) — be precise, not vague.

4. INDUSTRY NEWS (config.yaml -> industry_watch). Web-search for news about
   the listed companies' tabular-FM work: model releases, papers, funding,
   launches, benchmarks. Window: ONLY THE LAST 24 HOURS (lookback_days=1) —
   EXCEPT on Mondays, cover the LAST ~72 HOURS / Friday-Sunday
   (monday_lookback_days=3) to sweep the weekend. Include ONLY items
   genuinely published in that window AND that materially concern tabular
   FMs / tabular ML / relational FMs / neural processes. Verify each against
   a real dated URL — do NOT pad with older items or "context". Else use [].

5. SPOTLIGHT (config.yaml -> spotlight). Pick the one theme best supported
   by this issue's papers + industry news, and write a few concise
   sentences (<= ~90 words) on the current status of tabular foundation
   models in that vertical, grounded in this week's material. If there is
   too little to say, omit it.

6. Write digest.json in the repo root:
   {"window_label": "<from candidates.json>",
    "papers": [{id, title, authors, url, source, relevance_score,
                matched_author, matched_keyword, is_new_version,
                bullets: {problem, method, results, limitations}}],
    "industry": [{company, headline, date, url, summary}],   // [] if none
    "spotlight": {theme, body}}                               // omit if none
   Copy id/title/authors/url/source/matched_* fields verbatim from
   candidates.json. If NO paper scores >= 6, still write digest.json (empty
   papers list) — the industry/spotlight sections may still carry the issue.

7. Send it:  python -m newsletter.finalize digest.json
   This emails the digest and updates seen_papers.json. NOTE: finalize only
   sends when there is content — if BOTH papers and industry are empty (a
   fully quiet day) it deliberately sends NO email and just updates
   seen_papers.json. That is expected, not an error.

8. Commit and push seen_papers.json to the default branch with message
   "chore: update seen papers". Do NOT commit candidates.json or
   digest.json.

If a fetch source fails, proceed with whatever candidates you have. If a
web search for industry news fails, proceed with an empty industry list.
If SMTP fails, retry once, then leave the digest content in your final
summary so I can read it in the session.
```

## Notes

- Routines are in research preview and have per-account daily run caps;
  one run/day fits comfortably.
- The GitHub Actions path (README.md) remains fully functional if you
  ever prefer the deterministic scripted version — the two modes coexist
  in this repo.
