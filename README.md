# 🔭 Astro Daily Digest

A daily email digest of astrophysics papers from **Nature**, **Nature Astronomy**, and **The Astrophysical Journal Letters (ApJL)** — automatically fetched, summarized in Chinese using Claude AI, and delivered to your inbox every morning.

---

## What it does

Every day at 8:00 AM, the script:

1. Fetches new articles from Nature (astronomy-filtered), Nature Astronomy, and ApJL
2. Retrieves full text from arXiv (falls back to abstract if unavailable)
3. Generates a structured Chinese summary for each paper using Claude AI
4. Sends a formatted HTML email grouped by journal

Each paper summary includes:

- Title
- Plain-language introduction (2–3 sentences)
- Core physics question and its place in the field
- Methods, data, and key assumptions
- Main conclusions and strength of evidence
- Physical implications and broader impact
- Critical assessment: genuine contribution or incremental work?
- Items 1–10: Background / Scientific goal / Method / Results / Conclusion / Significance / Whether it touches fundamental physics / Whether it offers a new physical picture / Whether it addresses a major astrophysical problem / Whether the work is easily replaceable by AI

---

## Requirements

- Python 3.11+
- macOS (for cron scheduling; Linux also works)
- A running proxy (e.g. Clash) if you are in mainland China — needed for Gmail SMTP
- The following accounts/API keys:
  - [OpenRouter](https://openrouter.ai) account with API key (to call Claude)
  - Gmail account with [App Password](https://myaccount.google.com/apppasswords) enabled
  - [NASA ADS](https://ui.adsabs.harvard.edu) account with API token (free)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/LeniaChen/astro-daily-digest.git
cd astro-daily-digest
```

### 2. Install dependencies

```bash
pip install feedparser requests beautifulsoup4 openai PySocks
```

### 3. Configure credentials

Copy the example config file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```
OPENROUTER_API_KEY=your_openrouter_api_key
EMAIL_FROM=your_gmail@gmail.com
EMAIL_TO=your_gmail@gmail.com
EMAIL_PASSWORD=your_gmail_app_password_without_spaces
ADS_API_TOKEN=your_ads_api_token
```

> ⚠️ Never commit `.env` to git. It is already listed in `.gitignore`.

#### How to get each credential

| Credential | Where to get it |
|---|---|
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `EMAIL_PASSWORD` | Google Account → Security → 2-Step Verification → App Passwords |
| `ADS_API_TOKEN` | [ui.adsabs.harvard.edu](https://ui.adsabs.harvard.edu) → Account → API Token |

### 4. Test run

```bash
set -a && source .env && set +a && python3 digest.py
```

If everything is configured correctly, you will receive an email shortly.

---

## Automated daily delivery (macOS)

Make the run script executable:

```bash
chmod +x run.sh
```

Add a cron job to run at 8:00 AM daily:

```bash
crontab -e
```

Add this line:

```
0 8 * * * /path/to/astro-daily-digest/run.sh
```

Replace `/path/to/` with the actual path to the cloned folder (e.g. `/Users/yourname/astro-daily-digest`).

> The script uses a local Clash proxy on `127.0.0.1:7890` for Gmail SMTP. If you are not in mainland China or use a different proxy setup, edit the `send_email()` function in `digest.py` accordingly.

---

## Customization

### Change delivery time
Edit the cron expression. Format: `minute hour * * *`
```
30 7 * * *   # 7:30 AM
0  9 * * *   # 9:00 AM
```

### Add more RSS-based journals
In `digest.py`, add an entry to `RSS_SOURCES`:
```python
RSS_SOURCES = [
    ("Nature Astronomy", "https://www.nature.com/natastron.rss", False),
    ("Nature",           "https://www.nature.com/nature.rss",    True),
    ("Your Journal",     "https://your-journal-rss-url",         False),
]
```
The third parameter: `True` = filter by astronomy keywords, `False` = include all articles.

### Change the summary language or structure
Edit the `SUMMARY_PROMPT` variable in `digest.py`.

### Change recipient email
Edit `EMAIL_TO` in `.env`.

---

## File structure

```
astro-daily-digest/
├── digest.py            # Main script
├── run.sh               # Shell wrapper for cron
├── .env.example         # Credential template
├── .gitignore
└── README.md
```

Files generated at runtime (not tracked by git):
- `seen_articles.json` — tracks processed articles to avoid duplicates
- `digest.log` — daily run log

---

## Notes

- ApJL articles are fetched via [NASA ADS API](https://ui.adsabs.harvard.edu/help/api/) by current month's publication date. New articles added to ADS throughout the month will be picked up on subsequent runs.
- arXiv full text is preferred over abstracts. If an arXiv version is not found, the summary is generated from the abstract only, and the email will include a warning.
- The script uses `seen_articles.json` to track processed articles. Deleting this file will cause all current-month articles to be re-sent.

---

## License

MIT
