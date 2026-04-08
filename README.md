# 🔭 Astro Daily Digest

A daily email digest of astrophysics papers from **Nature**, **Nature Astronomy**, and **The Astrophysical Journal Letters (ApJL)** — automatically fetched, summarized using AI, and delivered to your inbox every morning.

Summaries are generated via [OpenRouter](https://openrouter.ai), which means you can use **any model** — Claude, GPT-4o, Gemini, DeepSeek, and more — simply by changing one line in the config.

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
- Any email account with SMTP access (Gmail, QQ Mail, 163, Outlook, etc.)
- The following accounts/API keys:
  - [OpenRouter](https://openrouter.ai) account with API key (to call the AI model)
  - Email account with SMTP enabled (see configuration below)
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
EMAIL_FROM=your_email@example.com
EMAIL_TO=your_email@example.com
EMAIL_PASSWORD=your_email_app_password

# SMTP settings
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465

# Proxy (see note below)
PROXY_HOST=
PROXY_PORT=7890

ADS_API_TOKEN=your_ads_api_token
```

> ⚠️ Never commit `.env` to git. It is already listed in `.gitignore`.

#### Supported email providers

| Provider | `SMTP_HOST` | `SMTP_PORT` |
|----------|-------------|-------------|
| Gmail | smtp.gmail.com | 465 |
| QQ Mail | smtp.qq.com | 465 |
| 163 Mail | smtp.163.com | 465 |
| Outlook | smtp.office365.com | 587 |

Most providers require you to generate an **App Password** (a dedicated password for third-party apps) rather than using your regular login password. Look for this option under your email account's security settings.

#### Do I need a proxy?

A proxy is only required if your SMTP provider is blocked in your region.

| Situation | Proxy needed? |
|-----------|---------------|
| Using Gmail from mainland China | **Yes** — Gmail SMTP is blocked |
| Using QQ / 163 / Outlook from mainland China | No |
| Outside mainland China | No |

If you need a proxy, set `PROXY_HOST=127.0.0.1` and `PROXY_PORT` to your local proxy port (e.g. Clash defaults to `7890`). Leave `PROXY_HOST` blank to disable the proxy.

#### How to get each credential

| Credential | Where to get it |
|---|---|
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `EMAIL_PASSWORD` | Your email provider's security settings → App Passwords |
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

> The proxy is only activated when `PROXY_HOST` is set in `.env`. If you don't need a proxy, leave it blank.

---

## Customization

### Change delivery time
Edit the cron expression. Format: `minute hour * * *`
```
30 7 * * *   # 7:30 AM
0  9 * * *   # 9:00 AM
```

### Add a journal with RSS feed

Many journals provide RSS feeds. To add one, open `digest.py` and add an entry to `RSS_SOURCES`:

```python
RSS_SOURCES = [
    ("Nature Astronomy", "https://www.nature.com/natastron.rss", False),
    ("Nature",           "https://www.nature.com/nature.rss",    True),
    ("Your Journal",     "https://your-journal-rss-url",         False),  # add here
]
```

The third parameter controls filtering:
- `False` — include all articles from this feed
- `True` — only include articles that match astronomy-related keywords (useful for broad journals like *Nature*)

Some RSS feed URLs for common journals:

| Journal | RSS URL |
|---------|---------|
| Nature Astronomy | https://www.nature.com/natastron.rss |
| Nature | https://www.nature.com/nature.rss |
| Science | https://www.science.org/rss/news_current.xml |
| MNRAS | https://academic.oup.com/rss/mnras |
| A&A | https://www.aanda.org/component/rss/?type=journal |

> **Note:** ApJ, ApJL, and ARA&A do not have accessible RSS feeds. Use the NASA ADS method below instead.

### Add a journal via NASA ADS (no RSS required)

For journals without accessible RSS feeds, you can use the NASA ADS API. The `fetch_apjl()` function in `digest.py` handles this. To add another journal, duplicate that function and change the `bibstem` value:

```python
def fetch_apj() -> list[dict]:
    month = date.today().strftime("%Y-%m")
    resp = requests.get(
        "https://api.adsabs.harvard.edu/v1/search/query",
        headers={"Authorization": f"Bearer {ADS_API_TOKEN}"},
        params={
            "q":    f"bibstem:ApJ pubdate:{month}",   # change ApJ to your journal
            "fl":   "title,bibcode,abstract,identifier,doi",
            "rows": 100,
            "sort": "date desc",
        },
        timeout=15,
    )
    # ... rest of function identical to fetch_apjl()
```

Common `bibstem` values:

| Journal | bibstem |
|---------|---------|
| ApJL | `ApJL` |
| ApJ | `ApJ` |
| ARA&A | `ARA+A` |
| AJ (Astronomical Journal) | `AJ` |
| MNRAS | `MNRAS` |
| A&A | `A&A` |

Then add the new function to the `main()` function:
```python
all_articles = fetch_rss() + fetch_apjl() + fetch_apj()
```

And add the journal name to `JOURNAL_ORDER` and `JOURNAL_COLORS` for proper email formatting.

### Filter articles by topic

You can instruct the AI to skip articles outside your area of interest. In `SUMMARY_PROMPT`, add a filter instruction at the top:

```python
SUMMARY_PROMPT = """\
...
If this paper is NOT related to [your topic, e.g. galaxy formation and evolution],
output exactly: 【SKIP】
Otherwise, proceed with the full summary below.
...
"""
```

Then in `main()`, add a check after summarizing:

```python
summary = summarize(title, content, is_abstract_only)
if "【SKIP】" in summary:
    print("  Skipping (not relevant).")
    seen.add(article["id"])
    save_seen(seen)
    continue
```

This way, irrelevant articles are silently skipped and will not appear in the email.

### Change the AI model
In `digest.py`, find the `summarize()` function and change the `model` parameter:
```python
model="anthropic/claude-opus-4"      # default
model="openai/gpt-4o"                # OpenAI
model="google/gemini-2.0-flash-001"  # Google, fast and cheap
model="deepseek/deepseek-r1"         # DeepSeek
```
See the full list of supported models at [openrouter.ai/models](https://openrouter.ai/models).

### Customize the summary structure or language
Edit the `SUMMARY_PROMPT` variable in `digest.py`. You can change the output language, add or remove sections, adjust the tone, or focus on specific aspects of the paper.

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
