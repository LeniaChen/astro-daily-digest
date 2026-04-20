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
DEEPSEEK_API_KEY   = os.environ["DEEPSEEK_API_KEY"]
EMAIL_FROM         = os.environ["EMAIL_FROM"]
EMAIL_TO           = os.environ["EMAIL_TO"]
EMAIL_PASSWORD     = os.environ["EMAIL_PASSWORD"]
ADS_API_TOKEN      = os.environ["ADS_API_TOKEN"]
SMTP_HOST          = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT          = int(os.environ.get("SMTP_PORT", "465"))
PROXY_HOST         = os.environ.get("PROXY_HOST", "")   # e.g. 127.0.0.1
PROXY_PORT         = int(os.environ.get("PROXY_PORT", "7890"))

SEEN_FILE = Path(__file__).parent / "seen_articles.json"

# RSS sources: (name, url, filter_astronomy)
RSS_SOURCES = [
    ("Nature Astronomy", "https://www.nature.com/natastron.rss",   False),
    ("Nature",           "https://www.nature.com/nature.rss",      True),
]

# arXiv categories to fetch daily
ARXIV_CATEGORIES = [
    "astro-ph.GA",   # Astrophysics of Galaxies
    "astro-ph.CO",   # Cosmology and Nongalactic Astrophysics
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

SIMPLE_SUMMARY_PROMPT = """\
你是一位天体物理学研究者。请用通俗直白简单的语言总结以下论文，面向非该细分领域的天体物理研究者。

论文标题：{title}

{content_label}：
{content}

请按以下格式输出，每项1-2句话，说最本质的内容，不废话：

【中文标题】论文标题的中文翻译

**工作内容**
这篇文章做了什么？

**主要结论**
得出了什么结论？

**意义**
这个结论有什么意义？
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
    """Fetch today's ApJL articles from NASA ADS."""
    today = date.today()
    month = today.strftime("%Y-%m")
    try:
        resp = requests.get(
            "https://api.adsabs.harvard.edu/v1/search/query",
            headers={"Authorization": f"Bearer {ADS_API_TOKEN}"},
            params={
                "q":    f"bibstem:ApJL pubdate:{month}",
                "fl":   "title,bibcode,abstract,identifier,doi,date",
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
        # Date filter: today only (ADS date field is like "2026-04-08T00:00:00Z")
        pub_date_str = doc.get("date", "")[:10]
        if pub_date_str != str(today):
            continue

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
            "arxiv_id": arxiv_id,
        })
    return articles


def fetch_arxiv_daily() -> list[dict]:
    """Fetch today's new submissions from arXiv RSS, then enrich with journal_ref/comment."""
    articles = []
    seen_ids: set = set()

    for category in ARXIV_CATEGORIES:
        url = f"https://rss.arxiv.org/rss/{category}"
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"  arXiv RSS error ({category}): {e}")
            continue
        for entry in feed.entries:
            raw_id = entry.get("id", entry.get("link", ""))
            if "/abs/" in raw_id:
                arxiv_id = raw_id.split("/abs/")[-1]
            elif "arXiv.org:" in raw_id:
                arxiv_id = raw_id.split("arXiv.org:")[-1]
            else:
                arxiv_id = raw_id
            arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
            if not arxiv_id or arxiv_id in seen_ids:
                continue
            seen_ids.add(arxiv_id)
            # Extract primary category from RSS tags
            tags = entry.get("tags", [])
            primary_cat = tags[0].get("term", "") if tags else ""
            articles.append({
                "title":       entry.title,
                "link":        f"https://arxiv.org/abs/{arxiv_id}",
                "abstract":    BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(),
                "id":          arxiv_id,
                "journal":     "arXiv",
                "arxiv_id":    arxiv_id,
                "journal_ref": "",
                "comment":     "",
                "categories":  primary_cat,
            })

    if not articles:
        return articles

    # Batch fetch journal_ref and comment from arXiv API
    id_list = ",".join(a["arxiv_id"] for a in articles)
    try:
        resp = requests.get(
            "http://export.arxiv.org/api/query",
            params={"id_list": id_list, "max_results": len(articles)},
            timeout=30,
        )
        if resp.status_code == 200:
            root = ET.fromstring(resp.text)
            ns = {
                "atom":  "http://www.w3.org/2005/Atom",
                "arxiv": "http://arxiv.org/schemas/atom",
            }
            meta = {}
            for entry in root.findall("atom:entry", ns):
                id_el = entry.find("atom:id", ns)
                if id_el is None:
                    continue
                aid = id_el.text.split("/abs/")[-1]
                aid = re.sub(r"v\d+$", "", aid)
                jr_el = entry.find("arxiv:journal_ref", ns)
                cm_el = entry.find("arxiv:comment", ns)
                meta[aid] = {
                    "journal_ref": jr_el.text.strip() if jr_el is not None else "",
                    "comment":     cm_el.text.strip() if cm_el is not None else "",
                }
            for a in articles:
                if a["arxiv_id"] in meta:
                    a["journal_ref"] = meta[a["arxiv_id"]]["journal_ref"]
                    a["comment"]     = meta[a["arxiv_id"]]["comment"]
    except Exception as e:
        print(f"  arXiv metadata fetch error: {e}")

    return articles


def extract_submission_info(journal_ref: str, comment: str) -> str:
    """Return a display string for journal status, or empty string if unknown."""
    if journal_ref:
        return f"📄 已发表：{journal_ref}"
    if comment:
        m = re.search(
            r"(?:submitted to|accepted (?:for publication )?(?:in|by))\s+([^,\.\n;]+)",
            comment, re.I,
        )
        if m:
            return f"📨 投稿至：{m.group(1).strip()}"
    return ""


def search_arxiv(title: str) -> "str | None":
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


def search_semantic_scholar_arxiv(title: str) -> "str | None":
    """Use Semantic Scholar fuzzy search to find arXiv ID. Fallback after search_arxiv fails."""
    try:
        resp = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": title, "fields": "externalIds", "limit": 3},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        for paper in resp.json().get("data", []):
            arxiv_id = paper.get("externalIds", {}).get("ArXiv")
            if arxiv_id:
                return arxiv_id
        return None
    except Exception as e:
        print(f"  Semantic Scholar error: {e}")
        return None


def fetch_arxiv_html(arxiv_id: str) -> "tuple[str, str] | tuple[None, str]":
    """Fetch and clean the HTML full text from arXiv.
    Returns (plain_text, keywords). text is None if fetch failed.
    keywords is '' if not found in the paper.
    """
    url = f"https://arxiv.org/html/{arxiv_id}"
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return None, ""
        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract keywords from ltx_classification div before removing elements
        keywords = ""
        for div in soup.find_all("div", class_="ltx_classification"):
            h6 = div.find("h6")
            if h6 and "keyword" in h6.get_text().lower():
                # Keywords are the text nodes directly inside the div, after the h6
                h6.decompose()
                keywords = div.get_text(separator=" ", strip=True)
                break

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
        return text, keywords
    except Exception as e:
        print(f"  arXiv HTML fetch error: {e}")
        return None, ""


def summarize(title: str, content: str, is_abstract_only: bool, is_ga: bool = True) -> str:
    client = OpenAI(
        base_url="https://api.deepseek.com",
        api_key=DEEPSEEK_API_KEY,
    )
    content_label = "摘要（注意：未找到全文，仅基于摘要总结，信息有限）" if is_abstract_only else "全文"
    prompt_template = SUMMARY_PROMPT if is_ga else SIMPLE_SUMMARY_PROMPT
    prompt = prompt_template.format(
        title=title,
        content_label=content_label,
        content=content,
    )
    max_tokens = 1800 if is_ga else 600
    for attempt in range(3):
        try:
            msg = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
                timeout=60,
            )
            result = msg.choices[0].message.content
            if is_abstract_only:
                result = "⚠️ **注意：arXiv 未找到全文，以下总结仅基于摘要，信息有限。**\n\n" + result
            return result
        except Exception as e:
            if attempt < 2:
                print(f"  总结超时，30秒后重试（第 {attempt + 1} 次）: {e}")
                time.sleep(30)
            else:
                raise


JOURNAL_ORDER = ["Nature", "Nature Astronomy", "ApJL", "arXiv"]
JOURNAL_COLORS = {
    "Nature":           "#8e44ad",
    "Nature Astronomy": "#c0392b",
    "ApJL":             "#2471a3",
    "arXiv":            "#b7950b",
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
            journal_info = extract_submission_info(
                item.get("journal_ref", ""), item.get("comment", "")
            )
            categories = item.get("categories", "")
            keywords   = item.get("keywords", "")
            meta_parts = []
            if categories:
                meta_parts.append(f"【相关领域】{categories}")
            if keywords:
                meta_parts.append(f"【关键词】{keywords}")
            meta_line = "&nbsp;&nbsp;|&nbsp;&nbsp;".join(meta_parts)
            parts += [
                f"<h2 style='color:#2d3561'>{i}. {item['title']}</h2>",
                f"<p style='color:#555;font-size:0.95em;margin-top:-0.5em'>{cn_title}</p>" if cn_title else "",
                f"<p style='color:#888;font-size:0.85em;margin-top:-0.4em'>{meta_line}</p>" if meta_line else "",
                f"<p style='color:#888;font-size:0.9em'>{journal_info}</p>" if journal_info else "",
                f"<p><a href='{item['link']}'>→ 原文链接</a></p>",
                f"<div style='line-height:1.7'>{summary_html}</div>",
                "<hr style='margin:1.5em 0'>",
            ]
    parts.append("</body></html>")
    return "\n".join(parts)


def send_email(subject: str, html_body: str):
    # Route through proxy if PROXY_HOST is set
    if PROXY_HOST:
        import socks
        import socket
        socks.set_default_proxy(socks.HTTP, PROXY_HOST, PROXY_PORT)
        socket.socket = socks.socksocket

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if SMTP_PORT == 587:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    else:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    seen = load_seen()

    # Gather all articles from all sources
    all_articles = fetch_rss() + fetch_apjl() + fetch_arxiv_daily()
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
        arxiv_id = article.get("arxiv_id")
        if not arxiv_id:
            arxiv_id = search_arxiv(title)
            time.sleep(1)  # be polite to arXiv API
        if not arxiv_id:
            print("  arXiv not found, trying Semantic Scholar...")
            arxiv_id = search_semantic_scholar_arxiv(title)
            if arxiv_id:
                print(f"  Semantic Scholar found arXiv ID: {arxiv_id}")
            time.sleep(1)

        full_text = None
        keywords  = ""
        if arxiv_id:
            print(f"  arXiv ID: {arxiv_id} — fetching HTML...")
            full_text, keywords = fetch_arxiv_html(arxiv_id)

        if full_text:
            content          = full_text
            is_abstract_only = False
            print("  Full text retrieved.")
        else:
            content          = article["abstract"]
            is_abstract_only = True
            print("  Falling back to abstract.")

        # Determine if GA article
        categories = article.get("categories", "")
        is_ga = "astro-ph.GA" in categories if categories else True  # non-arXiv默认用完整模板

        # 2. Summarize
        print("  Summarizing...")
        summary = summarize(title, content, is_abstract_only, is_ga=is_ga)
        summaries.append({
            "title":       title,
            "link":        article["link"],
            "summary":     summary,
            "journal":     article.get("journal", ""),
            "journal_ref": article.get("journal_ref", ""),
            "comment":     article.get("comment", ""),
            "categories":  categories,
            "keywords":    keywords,
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
