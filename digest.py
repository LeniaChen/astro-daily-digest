#!/usr/bin/env python3
"""
Nature Astronomy Daily Digest
- Fetches new articles from Nature Astronomy RSS
- Finds full text on arXiv (HTML), falls back to abstract
- Summarizes with Claude API using a 10-point template
- Sends via email
"""

import os
import json
import time
import smtplib
import re
import feedparser
import requests
from datetime import date
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from openai import OpenAI

# ── Config (from environment variables) ──────────────────────────────────────
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
EMAIL_FROM         = os.environ["EMAIL_FROM"]
EMAIL_TO           = os.environ["EMAIL_TO"]
EMAIL_PASSWORD     = os.environ["EMAIL_PASSWORD"]
ADS_API_TOKEN      = os.environ["ADS_API_TOKEN"]

SEEN_FILE = Path(__file__).parent / "seen_articles.json"

# RSS sources: (name, url, filter_astronomy)
RSS_SOURCES = [
    ("Nature Astronomy", "https://www.nature.com/natastron.rss",   False),
    ("Nature",           "https://www.nature.com/nature.rss",      True),
]

ASTRO_KEYWORDS = [
    "astro", "galaxy", "galaxies", "star", "stellar", "planet", "planetary",
    "cosmol", "telescope", "black hole", "neutron", "supernova", "pulsar",
    "quasar", "solar", "exoplanet", "nebula", "comet", "asteroid", "space",
    "universe", "dark matter", "dark energy", "gravitational", "spectral",
    "photometric", "redshift", "luminosity", "emission", "absorption",
    "interstellar", "intergalactic", "milky way", "andromeda", "hubble",
    "jwst", "webb", "chandra", "x-ray", "gamma-ray", "radio wave",
]

# ── Summary prompt ────────────────────────────────────────────────────────────
SUMMARY_PROMPT = """\
你是一位具有深厚物理直觉的天体物理学研究者。请对以下论文进行批判性结构化解读，用中文输出。语言精准，不废话，不美化。

论文标题：{title}

{content_label}：
{content}

请严格按以下顺序和格式输出，不要遗漏任何一项：

【中文标题】此处填写论文标题的中文翻译

**导读**
用2-3句话说清楚这篇文章在做什么、得到了什么结论、为什么值得关注。面向刚接触这个子领域的读者。

**核心物理问题**
这篇文章试图解答什么问题？这个问题在当前领域中处于什么位置——是开放的范式级问题，还是已有框架下的精修？

**方法与数据**
用什么方法、什么数据？关键假设是否成立？方法论上有无值得警惕的地方？

**主要结论**
结论是什么？证据链是否充分支撑结论，还是存在跳跃？

**物理意义**
这个结论改变了我们对哪个物理图像的理解？若结论成立，影响是局部的还是有更广泛的含义？

**你的判断**
这篇文章的核心贡献是什么？创新点是否是新的物理图像，还是仅仅"样本更大/方法更自动化"？有哪些值得追问的遗留问题？

---

1. **背景**
2. **科学目标**
3. **方法**
4. **结果**
5. **结论**
6. **意义与作用**
7. **是否触及基础物理问题**（是/否，说明原因）
8. **是否有新的物理图像**（是/否，说明原因）
9. **是否触及重大天体物理问题**（是/否，说明原因）
10. **这类工作是否容易被 AI 替代**（是/否，说明原因）
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(list(seen), ensure_ascii=False, indent=2))


def is_astronomy(entry) -> bool:
    text = (entry.title + " " + entry.get("summary", "")).lower()
    return any(kw in text for kw in ASTRO_KEYWORDS)


def fetch_rss() -> list[dict]:
    today = date.today()
    articles = []
    for journal_name, url, filter_astro in RSS_SOURCES:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            # Date filter: today only
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub_date = date(*entry.published_parsed[:3])
                if pub_date != today:
                    continue
            # Astronomy keyword filter (only for Nature full journal)
            if filter_astro and not is_astronomy(entry):
                continue
            articles.append({
                "title":    entry.title,
                "link":     entry.link,
                "abstract": BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(),
                "id":       entry.id,
                "journal":  journal_name,
            })
    return articles


def fetch_apjl() -> list[dict]:
    """Fetch this month's ApJL articles from NASA ADS, return unseen ones."""
    month = date.today().strftime("%Y-%m")
    try:
        resp = requests.get(
            "https://api.adsabs.harvard.edu/v1/search/query",
            headers={"Authorization": f"Bearer {ADS_API_TOKEN}"},
            params={
                "q":    f"bibstem:ApJL pubdate:{month}",
                "fl":   "title,bibcode,abstract,identifier,doi",
                "rows": 100,
                "sort": "date desc",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  ADS fetch error: {e}")
        return []

    docs = resp.json().get("response", {}).get("docs", [])
    articles = []
    for doc in docs:
        title = doc.get("title", [""])[0]
        bibcode = doc.get("bibcode", "")
        abstract = doc.get("abstract", "")
        # Extract arXiv ID from identifiers
        identifiers = doc.get("identifier", [])
        arxiv_id = next(
            (i.replace("arXiv:", "").replace("arxiv:", "") for i in identifiers if i.lower().startswith("arxiv:")),
            None,
        )
        articles.append({
            "title":    title,
            "link":     f"https://ui.adsabs.harvard.edu/abs/{bibcode}/abstract",
            "abstract": abstract,
            "id":       bibcode,
            "journal":  "ApJL",
            "arxiv_id": arxiv_id,  # pre-resolved, skip search_arxiv
        })
    return articles


def search_arxiv(title: str) -> str | None:
    """Return arXiv ID for the best title match, or None."""
    url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f'ti:"{title}"',
        "max_results": 1,
        "sortBy": "relevance",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        if not entries:
            return None
        id_url = entries[0].find("atom:id", ns).text  # e.g. http://arxiv.org/abs/2401.12345v2
        arxiv_id = id_url.split("/abs/")[-1]
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)  # strip version suffix
        return arxiv_id
    except Exception as e:
        print(f"  arXiv search error: {e}")
        return None


def fetch_arxiv_html(arxiv_id: str) -> str | None:
    """Fetch and clean the HTML full text from arXiv. Returns plain text or None."""
    url = f"https://arxiv.org/html/{arxiv_id}"
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove noisy elements
        for tag in soup.find_all(["script", "style", "nav", "footer", "figure", "table"]):
            tag.decompose()
        # Remove references section to save tokens
        for tag in soup.find_all(["section", "div"], id=re.compile(r"ref|bibliograph", re.I)):
            tag.decompose()
        # Get main article body
        body = (
            soup.find("article")
            or soup.find("div", class_=re.compile(r"ltx_document|ltx_page_main", re.I))
            or soup.body
        )
        text = (body or soup).get_text(separator="\n", strip=True)
        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Trim to ~10000 words to stay within token budget
        words = text.split()
        if len(words) > 10000:
            text = " ".join(words[:10000]) + "\n\n[全文已截断至前 10000 词]"
        return text
    except Exception as e:
        print(f"  arXiv HTML fetch error: {e}")
        return None


def summarize(title: str, content: str, is_abstract_only: bool) -> str:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )
    content_label = "摘要（注意：未找到全文，仅基于摘要总结，信息有限）" if is_abstract_only else "全文"
    prompt = SUMMARY_PROMPT.format(
        title=title,
        content_label=content_label,
        content=content,
    )
    msg = client.chat.completions.create(
        model="anthropic/claude-opus-4",
        max_tokens=1800,
        messages=[{"role": "user", "content": prompt}],
    )
    result = msg.choices[0].message.content
    if is_abstract_only:
        result = "⚠️ **注意：arXiv 未找到全文，以下总结仅基于摘要，信息有限。**\n\n" + result
    return result


JOURNAL_ORDER = ["Nature", "Nature Astronomy", "ApJL"]
JOURNAL_COLORS = {
    "Nature":           "#8e44ad",
    "Nature Astronomy": "#c0392b",
    "ApJL":             "#2471a3",
}

def build_html_email(summaries: list[dict]) -> str:
    today_str = date.today().strftime("%Y年%m月%d日")
    parts = [
        "<html><body style='font-family:sans-serif;max-width:860px;margin:auto;color:#222'>",
        f"<h1 style='color:#1a1a2e'>🔭 天体物理每日速览 — {today_str}</h1>",
        f"<p style='color:#555'>共 <b>{len(summaries)}</b> 篇新文章</p><hr>",
    ]

    # Group by journal in specified order
    from collections import defaultdict
    by_journal = defaultdict(list)
    for item in summaries:
        by_journal[item.get("journal", "其他")].append(item)

    for journal in JOURNAL_ORDER:
        items = by_journal.get(journal, [])
        if not items:
            continue
        color = JOURNAL_COLORS.get(journal, "#555")
        parts += [
            f"<h1 style='color:{color};border-bottom:3px solid {color};padding-bottom:8px;margin-top:2em'>"
            f"{journal} &nbsp;<span style='font-size:0.6em;font-weight:normal'>({len(items)} 篇)</span></h1>",
        ]
        for i, item in enumerate(items, 1):
            # Extract Chinese title from summary
            cn_title_match = re.search(r"【中文标题】\s*(.+)", item["summary"])
            cn_title = cn_title_match.group(1).strip() if cn_title_match else ""
            summary_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", item["summary"])
            summary_html = summary_html.replace("\n", "<br>")
            parts += [
                f"<h2 style='color:#2d3561'>{i}. {item['title']}</h2>",
                f"<p style='color:#555;font-size:0.95em;margin-top:-0.5em'>{cn_title}</p>" if cn_title else "",
                f"<p><a href='{item['link']}'>→ 原文链接</a></p>",
                f"<div style='line-height:1.7'>{summary_html}</div>",
                "<hr style='margin:1.5em 0'>",
            ]
    parts.append("</body></html>")
    return "\n".join(parts)


def send_email(subject: str, html_body: str):
    import socks
    import socket
    # Route through Clash local proxy (127.0.0.1:7890)
    socks.set_default_proxy(socks.HTTP, "127.0.0.1", 7890)
    socket.socket = socks.socksocket

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    seen = load_seen()

    # Gather all articles from all sources
    all_articles = fetch_rss() + fetch_apjl()
    new_articles = [a for a in all_articles if a["id"] not in seen]

    if not new_articles:
        print("No new articles today.")
        return

    print(f"Found {len(new_articles)} new article(s).")
    summaries = []

    for article in new_articles:
        title = article["title"]
        print(f"\nProcessing [{article.get('journal','')}]: {title}")

        # 1. Try arXiv full text
        # ApJL articles from ADS already have arxiv_id resolved
        arxiv_id = article.get("arxiv_id") or search_arxiv(title)
        if not article.get("arxiv_id"):
            time.sleep(1)  # be polite to arXiv API only when we searched

        full_text = None
        if arxiv_id:
            print(f"  arXiv ID: {arxiv_id} — fetching HTML...")
            full_text = fetch_arxiv_html(arxiv_id)

        if full_text:
            content          = full_text
            is_abstract_only = False
            print("  Full text retrieved.")
        else:
            content          = article["abstract"]
            is_abstract_only = True
            print("  Falling back to abstract.")

        # 2. Summarize
        print("  Summarizing...")
        summary = summarize(title, content, is_abstract_only)
        summaries.append({
            "title":   title,
            "link":    article["link"],
            "summary": summary,
            "journal": article.get("journal", ""),
        })
        seen.add(article["id"])
        save_seen(seen)  # save immediately after each article
        time.sleep(2)  # rate limit between API calls

    # 3. Send email
    today_str = date.today().strftime("%Y年%m月%d日")
    subject   = f"🔭 Nature Astronomy 速览 {today_str}（{len(summaries)} 篇）"
    html_body = build_html_email(summaries)
    print("\nSending email...")
    send_email(subject, html_body)
    save_seen(seen)
    print(f"Done. Sent {len(summaries)} summaries to {EMAIL_TO}.")


if __name__ == "__main__":
    main()
