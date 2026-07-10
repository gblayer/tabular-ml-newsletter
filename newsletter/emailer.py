"""Build the HTML digest and send it.

Transport is chosen by whichever credentials are present (see `send`):
  1. Gmail HTTPS API   — works behind a 443-only proxy (e.g. cloud routines)
  2. Resend HTTPS API  — needs a verified sender/domain
  3. SMTP              — local runs / GitHub Actions (Gmail app password)

The HTML is the "Forward Pass" design: dark ink masthead with a running
issue number, a "Today at a glance" index, full academic paper cards
(top one framed in blue), an industry section (top item framed in orange,
rest as compact rows), and a footer that is just the >>FP. mark. Everything
is inline-styled and degrades cleanly where a client strips web fonts.

Relevance scores and author-watch matches are internal — they never appear
in the email (see ROUTINE.md); they belong in the routine's chat summary.
"""
from __future__ import annotations

import base64
import os
import smtplib
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from .models import Paper

# ---------------------------------------------------------------------------
# Issue numbering
# ---------------------------------------------------------------------------
# Set these once to calibrate the running counter, then it advances by 1 on
# every publishing weekday — no state file, deterministic, dry-run safe.
# ISSUE_EPOCH = the date of the issue numbered ISSUE_START.
# Anchored to the launch issue: 2026-07-08 was issue #1.
ISSUE_EPOCH = date(2026, 7, 8)
ISSUE_START = 1
SEND_WEEKDAYS = {0, 1, 2, 3, 4}  # Mon–Fri (mirror config.yaml run.send_weekdays)


def _issue_number(now: datetime) -> int:
    end = now.date()
    if end <= ISSUE_EPOCH:
        return ISSUE_START
    count, cur = 0, ISSUE_EPOCH
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() in SEND_WEEKDAYS:
            count += 1
    return ISSUE_START + count


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
INK = "#17160f"
PAPER = "#f6f5f0"
DESK = "#e7e4da"
BODY = "#3f3d33"
MUTED = "#8b887c"
MUTED_LT = "#8f8c80"
RULE = "#e2e0d6"
RULE_HARD = "#cfcdc2"
RULE_IDX = "#dcdac0"
ACCENT = "#3b38f5"                 # blue
ACCENT2 = "#ff5a1f"                # orange
ACCENT_SOFT = "rgba(59,56,245,0.06)"
ACCENT2_SOFT = "rgba(255,90,31,0.08)"

DISPLAY = "'Space Grotesk','Helvetica Neue',Arial,sans-serif"
MONO = "'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
SANS = "'IBM Plex Sans',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

# Source labels. Kept monochrome (ink chip) to match the design.
SOURCE_BADGE = {
    "arxiv": ("arXiv", INK),
    "hf_daily": ("HF Daily", INK),
    "openreview": ("OpenReview", INK),
    "s2": ("SemScholar", INK),
}


def _authors(p: Paper) -> str:
    """All author names — no truncation."""
    return ", ".join(p.authors)


def _chip(text: str, bg: str, fg: str = "#ffffff") -> str:
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-family:{MONO};font-size:11px;font-weight:600;letter-spacing:.06em;'
        f'text-transform:uppercase;padding:3px 8px;">{text}</span>'
    )


def _section_header(num: str, label: str) -> str:
    return (
        f'<div style="border-bottom:2px solid {INK};padding-bottom:9px;margin:0 0 22px;">'
        f'<span style="font-family:{MONO};font-size:12px;font-weight:600;color:{ACCENT};">{num}</span>'
        f'<span style="font-family:{MONO};font-size:11.5px;font-weight:600;'
        f'letter-spacing:.16em;text-transform:uppercase;color:{INK};margin-left:14px;">{label}</span>'
        f'</div>'
    )


def _field(label: str, text: str, first: bool = False) -> str:
    if not text:
        return ""
    border = "" if first else f"border-top:1px solid {RULE};"
    return (
        f'<div style="{border}padding:12px 0;">'
        f'<div style="font-family:{MONO};font-size:10.5px;font-weight:600;'
        f'letter-spacing:.1em;text-transform:uppercase;color:{ACCENT};margin-bottom:6px;">{label}</div>'
        f'<div style="font-family:{SANS};font-size:14.5px;line-height:1.55;color:{BODY};">{text}</div>'
        f'</div>'
    )


def _paper_html(p: Paper, featured: bool = False) -> str:
    """One academic paper as a full card. The featured (top) card gets a blue frame."""
    badge, color = SOURCE_BADGE.get(p.source, (p.source, INK))
    b = p.bullets or {}
    version_note = (
        f' <span style="font-family:{MONO};font-size:11px;color:{MUTED};">(updated version)</span>'
        if p.is_new_version else ""
    )
    frame = (
        f"border:1.5px solid {ACCENT};background:{ACCENT_SOFT};"
        if featured else
        f"border:1.5px solid {INK};background:#ffffff;"
    )
    fields = (
        _field("Problem", b.get("problem", ""), first=True)
        + _field("Method", b.get("method", ""))
        + _field("Results", b.get("results", ""))
        + _field("Limitations", b.get("limitations", ""))
    )
    return f"""
    <div style="{frame}padding:22px;margin-bottom:22px;">
      <div style="margin-bottom:14px;">{_chip(badge, color)}{version_note}</div>
      <a href="{p.url}" style="display:block;font-family:{DISPLAY};font-size:22px;font-weight:600;
         line-height:1.2;letter-spacing:-.02em;color:{INK};text-decoration:none;">{p.title}</a>
      <div style="font-family:{MONO};font-size:12.5px;color:{MUTED};margin:9px 0 14px;">{_authors(p)}</div>
      {fields}
      <div style="border-top:1.5px solid {INK};margin-top:6px;padding-top:14px;">
        <a href="{p.url}" style="font-family:{MONO};font-size:12px;font-weight:600;
           letter-spacing:.06em;text-transform:uppercase;color:{ACCENT};text-decoration:none;">&raquo; Read paper</a>
      </div>
    </div>"""


def _industry_html(items: list[dict]) -> str:
    """First item is a featured orange-framed box; the rest are compact rows."""
    if not items:
        return ""
    first = items[0]
    company = (first.get("company") or "").strip()
    headline = (first.get("headline") or "").strip()
    date_s = (first.get("date") or "").strip()
    url = (first.get("url") or "").strip()
    summary = (first.get("summary") or "").strip()
    date_html = (
        f'<span style="font-family:{MONO};font-size:11px;color:{MUTED};"> &middot; {date_s}</span>'
        if date_s else ""
    )
    title_html = (
        f'<a href="{url}" style="color:{INK};text-decoration:none;">{headline}</a>' if url else headline
    )
    featured = f"""
    <div style="border:1.5px solid {ACCENT2};background:{ACCENT2_SOFT};padding:20px 22px;margin-bottom:20px;">
      <div style="margin-bottom:10px;">{_chip(company, ACCENT2)}{date_html}</div>
      <div style="font-family:{DISPLAY};font-size:20px;font-weight:600;letter-spacing:-.02em;
                  line-height:1.22;color:{INK};">{title_html}</div>
      <div style="font-family:{SANS};font-size:14.5px;line-height:1.55;color:{BODY};margin-top:9px;">{summary}</div>
    </div>"""

    rows = []
    for i, it in enumerate(items[1:]):
        c = (it.get("company") or "").strip()
        h = (it.get("headline") or "").strip()
        u = (it.get("url") or "").strip()
        s = (it.get("summary") or "").strip()
        line = f"{h} &mdash; {s}" if (h and s) else (h or s)
        line = f'<a href="{u}" style="color:{BODY};text-decoration:none;">{line}</a>' if u else line
        border = "" if i == 0 else f"border-top:1px solid {RULE_HARD};"
        rows.append(
            f"""
        <div style="{border}padding:12px 0;">
          <span style="display:inline-block;min-width:74px;font-family:{MONO};font-size:11px;
                       font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:{ACCENT2};">{c}</span>
          <span style="font-family:{SANS};font-size:14.5px;line-height:1.5;color:{BODY};">{line}</span>
        </div>"""
        )
    rest = f'<div style="border-top:1.5px solid {INK};">{"".join(rows)}</div>' if rows else ""
    return featured + rest


def _glance_html(spotlight: dict | None, papers: list[Paper], industry: list[dict] | None) -> str:
    """'Today at a glance' — a summary-of-the-summary: short one-line takeaways
    tagged Academia / Industry. Primary source is the routine's spotlight
    bullets; falls back to paper titles / an industry line if none were written."""
    sp = spotlight or {}
    academia = [str(x).strip() for x in (sp.get("academia") or []) if str(x).strip()]
    industry_b = [str(x).strip() for x in (sp.get("industry") or []) if str(x).strip()]

    entries: list[tuple[str, str, str]] = []  # (text, tag, tag_color)
    if academia or industry_b:
        entries += [(t, "Academia", ACCENT) for t in academia]
        entries += [(t, "Industry", ACCENT2) for t in industry_b]
    else:
        # Fallback when no spotlight bullets were written.
        entries += [(p.title, "Academia", ACCENT) for p in papers]
        if industry:
            n_up = len(industry)
            entries.append((f"{n_up} industry update" + ("s" if n_up != 1 else ""), "Industry", ACCENT2))

    if not entries:
        return ""

    row_html = []
    for i, (text, tag, tag_color) in enumerate(entries):
        border = "" if i == len(entries) - 1 else f"border-bottom:1px solid {RULE_IDX};"
        row_html.append(
            f"""
        <div style="{border}padding:9px 0;overflow:hidden;">
          <span style="float:left;font-family:{MONO};font-size:11px;font-weight:600;color:{ACCENT};">{i + 1:02d}</span>
          <span style="float:right;font-family:{MONO};font-size:10px;letter-spacing:.08em;
                       text-transform:uppercase;color:{tag_color};">{tag}</span>
          <div style="margin:0 96px 0 30px;font-family:{SANS};font-size:14px;line-height:1.4;color:{INK};">{text}</div>
        </div>"""
        )

    total = len(entries)
    items_label = f"{total} item" + ("s" if total != 1 else "")
    return f"""
    <div style="border:1.5px solid {INK};margin-bottom:44px;">
      <div style="background:{INK};color:{PAPER};padding:8px 14px;font-family:{MONO};font-size:10.5px;
                  font-weight:500;letter-spacing:.2em;text-transform:uppercase;overflow:hidden;">
        <span>Today at a glance</span><span style="float:right;color:{MUTED_LT};">{items_label}</span>
      </div>
      <div style="padding:4px 14px 8px;">{"".join(row_html)}</div>
    </div>"""


def build_html(
    papers: list[Paper],
    window_label: str,
    industry: list[dict] | None = None,
    spotlight: dict | None = None,   # accepted for compatibility; not rendered
    name: str = "Forward Pass",
) -> str:
    now = datetime.now()
    issue_no = _issue_number(now)
    subtitle = "Your daily digest of the top papers in tabular AI."

    glance = _glance_html(spotlight, papers, industry)

    # --- ordered, auto-numbered sections -----------------------------------
    blocks = []
    n = 1

    academic = _section_header(f"{n:02d}", "Academia")
    if papers:
        academic += "".join(_paper_html(p, featured=(i == 0)) for i, p in enumerate(papers))
    else:
        academic += (f'<p style="font-family:{SANS};color:{MUTED};font-size:14px;">'
                     f'No new papers today — quiet day.</p>')
    blocks.append(academic)
    n += 1

    if industry is not None:
        ind = _section_header(f"{n:02d}", "Industry")
        if industry:
            ind += _industry_html(industry)
        else:
            ind += (f'<p style="font-family:{SANS};color:{MUTED};font-size:14px;">'
                    f'No new updates in the industry today.</p>')
        blocks.append(ind)
        n += 1

    body_blocks = '<div style="height:36px;"></div>'.join(blocks)

    # Stacked masthead title: >>Forward / Pass.  (P sits under F)
    title = (
        f'<h1 style="margin:16px 0 0;font-family:{DISPLAY};font-weight:700;font-size:44px;'
        f'letter-spacing:-.025em;line-height:.98;text-transform:uppercase;color:{PAPER};">'
        f'<span style="color:{ACCENT};">&raquo;</span>Forward<br>'
        f'<span style="padding-left:31px;">Pass<span style="color:{ACCENT2};">.</span></span></h1>'
    )

    masthead = f"""
    <div style="background:{INK};color:{PAPER};padding:26px 40px 32px;">
      <div style="font-family:{MONO};font-size:10.5px;font-weight:500;letter-spacing:.22em;
                  text-transform:uppercase;color:{MUTED_LT};overflow:hidden;">
        <span>Daily &middot; Tabular AI</span>
        <span style="float:right;color:#c3c0b4;"><span style="color:{ACCENT};">&#9632;</span> Issue {issue_no} &middot; {now.strftime('%Y&middot;%m&middot;%d')}</span>
      </div>
      {title}
      <p style="margin:16px 0 0;font-family:{SANS};font-size:13px;color:#c3c0b4;line-height:1.4;">{subtitle}</p>
    </div>"""

    # Footer: only the >>FP. mark.
    footer = f"""
    <div style="background:{INK};padding:30px 40px;text-align:center;">
      <span style="font-family:{DISPLAY};font-weight:700;font-size:26px;letter-spacing:-.03em;
                   text-transform:uppercase;color:{PAPER};">
        <span style="color:{ACCENT};">&raquo;</span>FP<span style="color:{ACCENT2};">.</span>
      </span>
    </div>"""

    card = f"""
    <div style="max-width:640px;margin:0 auto;background:{PAPER};border:1.5px solid {INK};">
      {masthead}
      <div style="padding:38px 40px 12px;">
        {glance}
        {body_blocks}
      </div>
      {footer}
    </div>"""

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700'
        '&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" '
        'rel="stylesheet">'
        '<style>body{margin:0;padding:0;}a{text-decoration:none;}</style></head>'
        f'<body style="margin:0;padding:32px 12px;background:{DESK};">'
        f'{card}'
        '</body></html>'
    )


# ---------------------------------------------------------------------------
# Transport (unchanged)
# ---------------------------------------------------------------------------
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
RESEND_URL = "https://api.resend.com/emails"


def _recipients() -> list[str]:
    raw = os.environ["NEWSLETTER_TO"]
    return [a.strip() for a in raw.replace(";", ",").split(",") if a.strip()]


def _build_message(subject: str, html: str, sender: str, bcc: list[str] | None = None) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = sender
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg.attach(MIMEText(html, "html"))
    return msg


def _send_via_gmail_api(subject: str, html: str, sender: str, recipients: list[str]) -> None:
    token_resp = requests.post(
        GMAIL_TOKEN_URL,
        data={
            "client_id": os.environ["GMAIL_CLIENT_ID"],
            "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
            "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    token_resp.raise_for_status()
    access_token = token_resp.json()["access_token"]

    msg = _build_message(subject, html, sender, bcc=recipients)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    resp = requests.post(
        GMAIL_SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        json={"raw": raw},
        timeout=30,
    )
    resp.raise_for_status()


def _send_via_resend(subject: str, html: str, recipients: list[str]) -> None:
    resp = requests.post(
        RESEND_URL,
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={
            "from": os.environ.get("RESEND_FROM", "Forward Pass <onboarding@resend.dev>"),
            "to": recipients,
            "subject": subject,
            "html": html,
        },
        timeout=30,
    )
    resp.raise_for_status()


def _send_via_smtp(subject: str, html: str, sender: str, recipients: list[str],
                   smtp_host: str, smtp_port: int) -> None:
    password = os.environ["SMTP_PASSWORD"]
    msg = _build_message(subject, html, sender)
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())


def send(html: str, subject: str, smtp_host: str, smtp_port: int) -> None:
    sender = os.environ.get("SMTP_USER", "")
    recipients = _recipients()

    if os.environ.get("GMAIL_REFRESH_TOKEN"):
        _send_via_gmail_api(subject, html, sender, recipients)
    elif os.environ.get("RESEND_API_KEY"):
        _send_via_resend(subject, html, recipients)
    elif os.environ.get("SMTP_PASSWORD"):
        _send_via_smtp(subject, html, sender, recipients, smtp_host, smtp_port)
    else:
        raise RuntimeError(
            "No email transport configured: set GMAIL_REFRESH_TOKEN "
            "(+ GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET), or RESEND_API_KEY, "
            "or SMTP_PASSWORD."
        )
