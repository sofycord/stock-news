# 📈 Stock News — Daily AI Stock Briefing

A Python agent that sends a personalized daily stock market email every morning at **9:00 AM Panama time**. It pulls live stock data, fetches the latest news, and uses Claude AI to generate a clean briefing with portfolio updates and buy recommendations.

---

## What's in the email

- **Market Pulse** — quick overview of the day's market mood
- **Portfolio Update** — price, change, and key notes for each stock you own
- **Top News** — most relevant headlines across your holdings
- **Buy Recommendations** — 2 AI-picked stocks with reasoning and price targets

---

## Default portfolio

| Ticker | Company |
|--------|---------|
| NVDA | NVIDIA |
| RUM | Rumble |
| AMZN | Amazon |
| META | Meta |
| PLTR | Palantir |

---

## How it works

1. Fetches live prices and % changes via **Yahoo Finance** (`yfinance`)
2. Pulls the latest news headlines per stock
3. Sends everything to **Claude** (claude-sonnet-4-6) to write the briefing
4. Emails the formatted HTML report via **Gmail SMTP**
5. Runs daily on **GitHub Actions** — no server needed

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/sofycord/stock-news.git
cd stock-news
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
ANTHROPIC_API_KEY=sk-ant-...       # console.anthropic.com/settings/keys
SMTP_USER=your-gmail@gmail.com
SMTP_PASS=xxxx xxxx xxxx xxxx      # Google App Password (not your Gmail password)
RECIPIENT_EMAIL=you@example.com
```

> **Gmail App Password:** Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), create a password for "Mail", and paste the 16-character code.

### 4. Test it

```bash
python stock_news.py --now
```

This runs the full pipeline immediately and sends the email.

---

## Deploying with GitHub Actions (recommended)

The repo includes a workflow that runs daily at 9 AM Panama time (UTC-5).

1. Go to your repo → **Settings → Secrets and variables → Actions**
2. Add three repository secrets:
   - `ANTHROPIC_API_KEY`
   - `SMTP_USER`
   - `SMTP_PASS`
3. Push to `main` — the workflow activates automatically

To trigger manually: **Actions → Daily Stock Briefing → Run workflow**

---

## Customizing

**Change the portfolio** — edit `PORTFOLIO` in `stock_news.py`:
```python
PORTFOLIO: dict[str, str] = {
    "NVDA": "NVIDIA",
    "AMZN": "Amazon",
    # add or remove tickers here
}
```

**Change the schedule** — edit the cron line in `.github/workflows/daily-briefing.yml`:
```yaml
- cron: "0 14 * * *"   # 14:00 UTC = 9:00 AM UTC-5
```

**Change the recipient** — update `RECIPIENT_EMAIL` in your `.env` or GitHub secret.

---

## Stack

- [Claude API](https://anthropic.com) — AI briefing generation
- [yfinance](https://github.com/ranaroussi/yfinance) — live stock data
- [GitHub Actions](https://docs.github.com/en/actions) — daily scheduling
- Gmail SMTP — email delivery
