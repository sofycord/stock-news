"""
Stock News Daily Briefing
==========================
Fetches real-time stock data and news for a portfolio,
generates AI-powered analysis and buy recommendations via Claude,
and emails it daily at 9 AM Panama time.

Usage:
  python stock_news.py          # start APScheduler (fires daily at 9am Panama)
  python stock_news.py --now    # run once immediately (good for testing)
"""

import html as html_lib
import logging
import os
import re
import smtplib
import sys
import textwrap
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import yfinance as yf
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

PANAMA_TZ = pytz.timezone("America/Panama")  # UTC-5, no DST

PORTFOLIO: dict[str, str] = {
    "NVDA": "NVIDIA",
    "RUM":  "Rumble",
    "AMZN": "Amazon",
    "META": "Meta",
    "PLTR": "Palantir",
}

# Extra tickers available to Claude when making buy recommendations
WATCHLIST = ["AAPL", "MSFT", "GOOGL", "TSLA", "AMD", "SMCI", "COIN", "SHOP", "UBER", "SOFI"]

ALL_TICKERS = list(PORTFOLIO.keys()) + WATCHLIST


# ── Step 1: Fetch stock data ──────────────────────────────────────────────────

def fetch_stock_data(tickers: list[str]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for ticker in tickers:
        try:
            fi = yf.Ticker(ticker).fast_info
            price      = fi.last_price
            prev_close = fi.previous_close

            if price is None or prev_close is None:
                log.warning("%s: missing price data — skipping", ticker)
                continue

            change     = price - prev_close
            pct_change = (change / prev_close) * 100

            results[ticker] = {
                "name":       PORTFOLIO.get(ticker, ticker),
                "price":      price,
                "change":     change,
                "pct_change": pct_change,
                "52w_high":   getattr(fi, "year_high", None),
                "52w_low":    getattr(fi, "year_low",  None),
                "market_cap": getattr(fi, "market_cap", None),
            }
            log.info("%-5s  $%8.2f  %+.2f%%", ticker, price, pct_change)
        except Exception as exc:
            log.warning("Failed to fetch %s: %s", ticker, exc)

    return results


def fetch_stock_news(tickers: list[str]) -> list[dict]:
    seen:  set[str]  = set()
    items: list[dict] = []

    for ticker in tickers:
        try:
            news = yf.Ticker(ticker).news or []
            for item in news[:5]:
                # yfinance >= 0.2.50 nests data under item["content"]
                content   = item.get("content", item)
                title     = content.get("title", "")
                publisher = (
                    content.get("provider", {}).get("displayName", "")
                    or item.get("publisher", "")
                )
                if not title or title.lower() in seen:
                    continue
                seen.add(title.lower())
                items.append({
                    "ticker":    ticker,
                    "name":      PORTFOLIO.get(ticker, ticker),
                    "title":     title,
                    "publisher": publisher,
                })
        except Exception as exc:
            log.warning("News fetch failed for %s: %s", ticker, exc)

    return items[:25]


# ── Step 2: Generate briefing via Claude ─────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent("""\
    You write a daily stock market briefing for a personal investor.
    The investor's current portfolio: NVIDIA (NVDA), Rumble (RUM), Amazon (AMZN), \
    Meta (META), Palantir (PLTR).

    Use these exact ## section headers in order:

    ## Market Pulse
    2–3 sentences on the overall market mood today and any macro backdrop.

    ## Portfolio Update
    One short paragraph per stock: price move, what's likely driving it, what to watch.
    Show price and % change inline — e.g. NVDA $892.45 ▲ +2.3%.

    ## Top News
    3–5 of the most impactful news items across the portfolio. One line each.

    ## Buy Recommendations
    Exactly 2 picks. For each: ticker, current price, why now, and a brief \
    price target or near-term catalyst. You may pick from the portfolio or \
    from the watchlist data provided.

    Rules:
    - Under 650 words total.
    - Use the real prices and % changes from the data provided — be specific.
    - Confident, direct tone — like a sharp buy-side analyst.
    - No disclaimers or hedging language.\
""")


def generate_briefing(stock_data: dict, news_items: list[dict]) -> str:
    client    = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today_str = datetime.now(PANAMA_TZ).strftime("%A, %B %d, %Y")

    # Portfolio block
    portfolio_lines: list[str] = []
    for ticker in PORTFOLIO:
        if ticker not in stock_data:
            continue
        d     = stock_data[ticker]
        arrow = "▲" if d["change"] >= 0 else "▼"
        hl    = ""
        if d.get("52w_high") and d.get("52w_low"):
            hl = f" | 52w: ${d['52w_low']:.2f}–${d['52w_high']:.2f}"
        portfolio_lines.append(
            f"{d['name']} ({ticker}): ${d['price']:.2f} "
            f"{arrow} {d['change']:+.2f} ({d['pct_change']:+.2f}%){hl}"
        )

    # Watchlist block (for recommendations)
    watchlist_lines: list[str] = []
    for ticker in WATCHLIST:
        if ticker not in stock_data:
            continue
        d     = stock_data[ticker]
        arrow = "▲" if d["change"] >= 0 else "▼"
        watchlist_lines.append(
            f"{ticker}: ${d['price']:.2f} {arrow} {d['pct_change']:+.2f}%"
        )

    news_lines = [
        f"[{n['name']}] {n['title']} ({n['publisher']})"
        for n in news_items
    ]

    user_content = (
        f"Today is {today_str}.\n\n"
        f"PORTFOLIO:\n" + "\n".join(portfolio_lines) + "\n\n"
        + "WATCHLIST (for recommendations):\n" + "\n".join(watchlist_lines) + "\n\n"
        + "TODAY'S NEWS:\n" + "\n".join(news_lines) + "\n\n"
        + "Write the daily briefing now."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    text = response.content[0].text.strip()
    log.info("Briefing generated: %d words", len(text.split()))
    return text


# ── Step 3: Build and send the email ─────────────────────────────────────────

def _md_to_html(text: str) -> str:
    text = html_lib.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         text)
    text = re.sub(
        r"^## (.+)$",
        r"<h2 style='margin:26px 0 8px;font-size:15px;font-family:Arial,sans-serif;"
        r"text-transform:uppercase;letter-spacing:1px;color:#93c5fd;"
        r"border-bottom:1px solid #334155;padding-bottom:6px;'>\1</h2>",
        text,
        flags=re.MULTILINE,
    )
    text = text.replace("▲", "<span style='color:#4ade80;font-weight:700;'>▲</span>")
    text = text.replace("▼", "<span style='color:#f87171;font-weight:700;'>▼</span>")

    blocks     = re.split(r"\n{2,}", text)
    html_blocks: list[str] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if re.match(r"^<h[1-3]", block):
            html_blocks.append(block)
        else:
            html_blocks.append(
                f"<p style='margin:0 0 14px;'>{block.replace(chr(10), '<br>')}</p>"
            )
    return "\n".join(html_blocks)


def build_html_email(briefing_text: str, date_str: str) -> str:
    body = _md_to_html(briefing_text)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Stock News — {date_str}</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;font-family:Georgia,'Times New Roman',serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;padding:32px 16px;">
    <tr><td align="center">
      <table width="620" cellpadding="0" cellspacing="0"
             style="background:#1e293b;border-radius:8px;
                    box-shadow:0 4px 24px rgba(0,0,0,.5);overflow:hidden;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#1d4ed8 0%,#0ea5e9 100%);
                     padding:24px 32px 20px;">
            <p style="margin:0 0 4px;font-family:Arial,Helvetica,sans-serif;
                      font-size:10px;letter-spacing:2.5px;text-transform:uppercase;
                      color:rgba(255,255,255,.65);">
              Daily Stock Briefing
            </p>
            <p style="margin:0;font-family:Arial,Helvetica,sans-serif;
                      font-size:22px;font-weight:700;color:#ffffff;">
              &#x1F4C8;&nbsp; {date_str}
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:28px 32px 6px;color:#cbd5e1;font-size:15px;line-height:1.85;">
            {body}
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:16px 32px 24px;border-top:1px solid #334155;">
            <p style="margin:0;font-family:Arial,Helvetica,sans-serif;
                      font-size:11px;color:#475569;line-height:1.6;">
              Portfolio: NVDA &middot; RUM &middot; AMZN &middot; META &middot; PLTR
              &nbsp;&middot;&nbsp; Data via Yahoo Finance
              &nbsp;&middot;&nbsp; Analysis by Claude (claude-sonnet-4-6)
              &nbsp;&middot;&nbsp; {date_str}
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_email(subject: str, plain_text: str, html_text: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    recipient = os.environ.get("RECIPIENT_EMAIL", "pedrocordovez@ovni.com")

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Stock News <{smtp_user}>"
    msg["To"]      = recipient
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_text,  "html",  "utf-8"))

    log.info("Sending to %s via %s:%s …", recipient, smtp_host, smtp_port)
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [recipient], msg.as_string())

    log.info("✓ Email delivered to %s", recipient)


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_briefing() -> None:
    now      = datetime.now(PANAMA_TZ)
    date_str = now.strftime("%A, %B %d, %Y")
    log.info("══ Stock News briefing for %s ══", date_str)

    log.info("Fetching stock data …")
    stock_data = fetch_stock_data(ALL_TICKERS)

    if not stock_data:
        log.error("No stock data fetched — aborting.")
        return

    log.info("Fetching news …")
    news_items = fetch_stock_news(list(PORTFOLIO.keys()))

    briefing = generate_briefing(stock_data, news_items)
    subject  = f"📈 Stock News — {now.strftime('%a, %b %d')}"
    html     = build_html_email(briefing, date_str)
    send_email(subject, briefing, html)

    log.info("══ Done ══")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--now" in sys.argv:
        run_briefing()
    else:
        scheduler = BlockingScheduler(timezone=PANAMA_TZ)
        scheduler.add_job(run_briefing, "cron", hour=9, minute=0)
        log.info("Scheduler running — briefing fires daily at 09:00 AM Panama time.")
        log.info("Tip: run with --now to send immediately without waiting.")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            log.info("Scheduler stopped.")
