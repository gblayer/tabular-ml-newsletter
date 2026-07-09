"""Build the HTML digest and send it.

Transport is chosen by whichever credentials are present (see `send`):
  1. Gmail HTTPS API   — works behind a 443-only proxy (e.g. cloud routines)
  2. Resend HTTPS API  — needs a verified sender/domain
  3. SMTP              — local runs / GitHub Actions (Gmail app password)
"""
from __future__ import annotations

import base64
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from .models import Paper

SOURCE_BADGE = {
    "arxiv": ("arXiv", "#B31B1B"),
    "hf_daily": ("HF Daily", "#FF9D00"),
    "openreview": ("OpenReview", "#8B1A1A"),
    "s2": ("SemScholar", "#1857B6"),
}


def _paper_html(p: Paper) -> str:
    badge, color = SOURCE_BADGE.get(p.source, (p.source, "#666"))
    b = p.bullets or {}
    via = ""
    if p.matched_author:
        via = f'<span style="color:#888;font-size:12px;"> · via author watch: {p.matched_author}</span>'
    elif p.matched_keyword and p.matched_keyword.startswith("cites"):
        via = f'<span style="color:#888;font-size:12px;"> · {p.matched_keyword}</span>'
    version_note = ' <span style="color:#888;font-size:12px;">(updated version)</span>' if p.is_new_version else ""
    # Results sits between method and limitations; rendered only when present
    # so older/thin digests degrade gracefully.
    results_li = f"<li><b>Results:</b> {b['results']}</li>" if b.get("results") else ""
    return f"""
    <div style="margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid #eee;">
      <div style="margin-bottom:6px;">
        <span style="background:{color};color:#fff;border-radius:3px;padding:1px 6px;
                     font-size:11px;vertical-align:middle;">{badge}</span>
        <span style="color:#888;font-size:12px;"> score {p.relevance_score}/10</span>{via}
      </div>
      <a href="{p.url}" style="font-size:16px;font-weight:600;color:#1a1a1a;
         text-decoration:none;">{p.title}</a>{version_note}
      <div style="color:#666;font-size:13px;margin:4px 0 10px;">{p.short_authors()}</div>
      <ul style="margin:0;padding-left:18px;font-size:14px;line-height:1.5;color:#333;">
        <li><b>Problem:</b> {b.get('problem','')}</li>
        <li><b>Method:</b> {b.get('method','')}</li>
        {results_li}
        <li><b>Limitations:</b> {b.get('limitations','')}</li>
      </ul>
      <div style="margin-top:8px;"><a href="{p.url}" style="font-size:13px;color:#1857B6;">→ paper</a></div>
    </div>"""


def _section_header(text: str) -> str:
    return (
        f'<h3 style="font-weight:600;font-size:15px;color:#1a1a1a;margin:32px 0 12px;'
        f'padding-bottom:6px;border-bottom:2px solid #1a1a1a;">{text}</h3>'
    )


def _industry_html(items: list[dict]) -> str:
    rows = []
    for it in items:
        company = (it.get("company") or "").strip()
        headline = (it.get("headline") or "").strip()
        date = (it.get("date") or "").strip()
        url = (it.get("url") or "").strip()
        summary = (it.get("summary") or "").strip()
        title_html = (
            f'<a href="{url}" style="color:#1a1a1a;text-decoration:none;">{headline}</a>'
            if url else headline
        )
        date_html = f'<span style="color:#888;font-size:12px;"> · {date}</span>' if date else ""
        rows.append(
            f"""
        <div style="margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid #eee;">
          <div style="margin-bottom:4px;">
            <span style="background:#0B7285;color:#fff;border-radius:3px;padding:1px 6px;
                         font-size:11px;">{company}</span>{date_html}
          </div>
          <div style="font-size:15px;font-weight:600;">{title_html}</div>
          <div style="color:#333;font-size:14px;line-height:1.5;margin-top:4px;">{summary}</div>
        </div>"""
        )
    return "".join(rows)


def _spotlight_html(spotlight: dict) -> str:
    theme = (spotlight.get("theme") or "").strip()
    body = (spotlight.get("body") or "").strip()
    if not body:
        return ""
    return f"""
    <div style="margin:32px 0;padding:16px 18px;background:#f6f8fa;border-radius:6px;
                border-left:4px solid #6741D9;">
      <div style="font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:#6741D9;
                  font-weight:600;margin-bottom:6px;">🔬 Spotlight · {theme}</div>
      <div style="font-size:14px;line-height:1.55;color:#333;">{body}</div>
    </div>"""


def build_html(
    papers: list[Paper],
    window_label: str,
    industry: list[dict] | None = None,
    spotlight: dict | None = None,
    name: str = "Forward Pass",
) -> str:
    if papers:
        subtitle = "Your daily digest of the top papers in tabular AI"
        academic_block = _section_header("📄 Academic — new papers") + "".join(
            _paper_html(p) for p in papers
        )
    else:
        subtitle = "Your daily digest of tabular AI papers"
        academic_block = '<p style="color:#555;font-size:14px;">No new papers today — quiet day. ☕</p>'

    # industry is None -> section omitted (e.g. API mode); [] -> explicit
    # "no updates" note; [items] -> the news. So on a sent issue the industry
    # section is always present, matching the daily-digest rules.
    industry_block = ""
    if industry is not None:
        if industry:
            industry_block = _section_header("🏢 Industry — today") + _industry_html(industry)
        else:
            industry_block = _section_header("🏢 Industry — today") + (
                '<p style="color:#555;font-size:14px;">No new updates in the industry today.</p>'
            )

    # Spotlight leads the issue (top), then the academic papers, then industry.
    spotlight_block = _spotlight_html(spotlight) if spotlight else ""

    return f"""
    <div style="max-width:640px;margin:0 auto;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">
      <h2 style="font-weight:600;margin-bottom:2px;">⏩ {name}</h2>
      <div style="color:#888;font-size:13px;margin-bottom:16px;">{subtitle}</div>
      {spotlight_block}
      {academic_block}
      {industry_block}
      <p style="color:#aaa;font-size:12px;margin-top:28px;">Generated {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
      · edit config.yaml in the repo to tune topics, authors and volume.</p>
    </div>"""


GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
RESEND_URL = "https://api.resend.com/emails"


def _recipients() -> list[str]:
    # NEWSLETTER_TO may be a single address or a comma/semicolon-separated list.
    raw = os.environ["NEWSLETTER_TO"]
    return [a.strip() for a in raw.replace(";", ",").split(",") if a.strip()]


def _build_message(subject: str, html: str, sender: str, bcc: list[str] | None = None) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    # Show only the sender in the visible To: header — recipients stay private.
    msg["To"] = sender
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg.attach(MIMEText(html, "html"))
    return msg


def _send_via_gmail_api(subject: str, html: str, sender: str, recipients: list[str]) -> None:
    """Gmail HTTPS API. Exchanges the refresh token for an access token, then
    posts the raw MIME message. Delivery follows the To/Bcc headers, so
    recipients go in Bcc to stay private. Works where raw SMTP :587 is blocked."""
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
    """Resend HTTPS API. `from` must be a Resend-verified sender/domain."""
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
    msg = _build_message(subject, html, sender)  # recipients via SMTP envelope
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())


def send(html: str, subject: str, smtp_host: str, smtp_port: int) -> None:
    """Deliver the digest via whichever transport is configured (priority
    order): Gmail HTTPS API, Resend HTTPS API, then SMTP. The HTTPS options
    work in sandboxes that only allow port 443 (where raw SMTP is blocked)."""
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
