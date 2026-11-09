"""Public table-of-contents monitor for seven Chinese economics journals.

This is a conservative discovery aid, NOT publication-date verification.
Publisher pages are preferred where available; NCPS SD is an authoritative
catalog fallback, not the journal publisher. No login/paywall bypass.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

# Each URL is a public journal table of contents or an authoritative catalog.
# Catalog-only coverage is deliberately reported as partial, never as a
# successful full-text or article-level scan.
JOURNALS = (
    ("economic_research", "经济研究", "catalog", "https://www.ncpssd.org/journal/details?gch=95645X"),
    ("china_industrial", "中国工业经济", "catalog", "https://ncpssd.org/journal/details.aspx?gch=93800A"),
    ("management_world", "管理世界", "catalog", "https://m.ncpssd.cn/journal/details?gch=95499X&langType=1&nav=1"),
    ("world_economy", "世界经济", "publisher", "https://sjjj.magtech.com.cn/CN/home"),
    ("quant_economics", "数量经济技术经济研究", "catalog", "https://www.ncpssd.org/journal/details?gch=94503X"),
    ("finance_economics", "财经研究", "publisher", "https://qks.sufe.edu.cn/J/CJYJ/Article/CurrentIssue/CN"),
    ("financial_research", "金融研究", "publisher", "https://www.jryj.org.cn/CN/1002-7246/current.shtml"),
)

FALLBACKS = {
    "financial_research": ("catalog", "https://m.ncpssd.cn/journal/details?gch=97926X&langType=1&nav=1"),
}

ONLINE_RE = re.compile(r"在线出版日期\s*[:：]\s*(20\d{2})年(\d{1,2})月(\d{1,2})日")
DOI_RE = re.compile(r"10\.\d{4,9}/[A-Za-z0-9._;()/:+-]+", re.I)

ISSUE_RE = re.compile(r"(20\d{2})\s*年[^\n]{0,40}?第\s*(0?[1-9]|1[0-2])\s*期")
DATE_RE = re.compile(r"(?:刊出日期|出版日期)\s*[:：]\s*(20\d{2}-\d{2}-\d{2})")
BAD_TITLES = ("当期目录", "过刊浏览", "摘要点击", "全文下载", "期刊介绍", "下载全文",
              "复现包", "补充材料", "作者在线", "在线投稿", "责任编辑", "目录文件",
              "更多信息", "发表文章", "摘要", "文献中心", "联系我们")


class TocHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.anchor_parts = []

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        if self.href is not None:
            self.anchor_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            if self.href:
                self.links.append((" ".join(" ".join(self.anchor_parts).split()), self.href))
            self.href = None
            self.anchor_parts = []


def fetch_html(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AcademicResearchRadar/0.2 (public journal metadata monitor)",
                 "Accept": "text/html,application/xhtml+xml"},
    )
    with urllib.request.urlopen(request, timeout=14) as response:
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            raise ValueError("unexpected_content_type: " + content_type[:60])
        return response.read(2_000_001)


def article_link(kind: str, url: str) -> bool:
    path = urllib.parse.urlparse(url).path
    if kind == "catalog":
        # National catalog may expose an issue but not verifiable article pages.
        # Do not mistake download links, buttons or site navigation for papers.
        return bool(re.search(r"/(?:article|literature|paper)/[A-Za-z0-9_-]{8,}", path, re.I))
    if "/J/CJYJ/" in path:
        # SUFE issue links look like /Article/2026/09/CN and must NOT be
        # mistaken for articles. Real detail links use /Article/Details/<id>/CN.
        return bool(re.fullmatch(r"/J/CJYJ/Article/Details/[A-Za-z0-9_-]{12,}/CN", path, re.I))
    return bool(re.search(r"/CN/Y20\d{2}/|/CN/10\.\d{4,9}/", path, re.I))


def parse_toc(payload: bytes, *, journal: str, kind: str, url: str) -> tuple[str | None, str | None, list[dict]]:
    parser = TocHTML()
    parser.feed(payload.decode("utf-8-sig", errors="replace"))
    text = "\n".join(parser.text_parts)
    if journal not in text:
        return None, None, []
    issues = ISSUE_RE.findall(text)
    # Homepage content can contain prior issues; take the latest issue for
    # the year and reject year/month regression later in scan().
    issue = max((f"{y}-{int(m):02d}" for y, m in issues), default=None)
    date_match = DATE_RE.search(text)
    issue_date = date_match.group(1) if date_match else None
    articles: list[dict] = []
    links: list[tuple[str, str, int]] = []
    seen_urls: set[str] = set()
    for title, href in parser.links:
        absolute = urllib.parse.urljoin(url, html.unescape(href))
        if urllib.parse.urlparse(absolute).hostname != urllib.parse.urlparse(url).hostname:
            continue
        if not article_link(kind, absolute):
            continue
        title = " ".join(title.split())
        if not 8 <= len(title) <= 150 or not re.search(r"[\u3400-\u9fff]", title):
            continue
        if any(junk in title for junk in BAD_TITLES) or absolute in seen_urls:
            continue
        position = text.find(title)
        if position < 0:
            continue
        seen_urls.add(absolute)
        links.append((title, absolute, position))
    links.sort(key=lambda x: x[2])
    for index, (title, absolute, position) in enumerate(links):
        following = links[index + 1][2] if index + 1 < len(links) else len(text)
        section = text[position:min(following, position + 1600)]
        published = None
        match = ONLINE_RE.search(section)
        if match:
            y, m, d = map(int, match.groups())
            try:
                published = datetime(y, m, d).date().isoformat()
            except ValueError:
                pass
        doi_match = DOI_RE.search(section) if kind == "publisher" else None
        articles.append({"title": title, "url": absolute, "published_at": published,
                         "doi": doi_match.group(0).rstrip(".,;") if doi_match else None})
    return issue, issue_date, articles


def scan_chinese_journals(out: Path, now: datetime, get=fetch_html) -> dict:
    """Monitor each journal independently; never infer publication from first_seen."""
    seen_path = out / "chinese_seen.json"
    seen = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {}
    if not isinstance(seen, dict):
        raise ValueError("chinese_seen.json must be an object")
    updated = dict(seen)
    journals: dict[str, dict] = {}
    new_items: list[dict] = []
    full_ok = 0
    records = 0
    failures = []
    checked = now.date().isoformat()
    for slug, journal, kind, url in JOURNALS:
        info = {"journal": journal, "source_kind": kind, "url": url, "checked_at": now.isoformat(),
                "status": "not_run", "issue": None, "issue_date": None, "article_count": 0}
        previous = seen.get(slug, {})
        try:
            try:
                payload = get(url)
            except (OSError, ValueError) as primary_error:
                if slug not in FALLBACKS:
                    raise
                fallback_kind, fallback_url = FALLBACKS[slug]
                payload = get(fallback_url)
                info["primary_url"] = url
                info["primary_failure"] = f"{type(primary_error).__name__}: {str(primary_error)[:140]}"
                info["url"] = url = fallback_url
                info["source_kind"] = kind = fallback_kind
            issue, issue_date, articles = parse_toc(payload, journal=journal, kind=kind, url=url)
            if not issue:
                info.update(status="unverified", reason="journal_or_issue_not_recognized")
            elif previous.get("issue") and issue < previous["issue"]:
                info.update(status="stale_index", issue=issue, reason="catalog_regressed")
            else:
                info.update(issue=issue, issue_date=issue_date, article_count=len(articles),
                            status="ok" if articles else "catalog_only")
                if not articles:
                    info["reason"] = "issue_visible_but_articles_not_verified"
                if info.get("primary_failure"):
                    info["reason"] = "publisher_unavailable; " + info.get("reason", "catalog_fallback")
                previous_articles = set(previous.get("articles", []))
                current = set(previous_articles)
                for article in articles:
                    title_key = re.sub(r"[^\w]", "", article["title"]).casefold()
                    if title_key in current:
                        continue
                    current.add(title_key)
                    recent_published = bool(article.get("published_at") and
                                           now.date() - timedelta(days=14) <=
                                           datetime.fromisoformat(article["published_at"]).date() <= now.date())
                    if previous.get("baselined") or recent_published:
                        ident = hashlib.sha256((slug + ":" + title_key).encode()).hexdigest()[:16]
                        new_items.append({
                            "id": "journal:" + slug + ":" + ident,
                            "title": article["title"],
                            "journal": journal,
                            "url": article["url"],
                            "source": "chinese_journal_toc",
                            "source_kind": kind,
                            "issue": issue,
                            "issue_date": issue_date,
                            "published_at": article.get("published_at"),
                            "doi": article.get("doi"),
                            "first_observed_at": checked,
                            "event_type": "publisher_online_date" if article.get("published_at") else "first_seen_in_toc",
                            "date_verified": bool(article.get("published_at")),
                            "note": "First observation is not publication; publisher online date is verified where available.",
                        })
                updated[slug] = {"issue": issue, "articles": sorted(current), "baselined": True,
                                 "last_success_at": now.isoformat()}
                if articles:
                    full_ok += 1
                    records += len(articles)
        except (OSError, ValueError, UnicodeError) as error:
            info.update(status="failed", reason=f"{type(error).__name__}: {str(error)[:120]}")
        if info["status"] != "ok":
            failures.append(f"{journal}: {info['status']} ({info.get('reason', '')})")
        journals[slug] = info
    source_status = {"status": "ok" if full_ok == len(JOURNALS) else "degraded" if any(
        j["status"] in ("ok", "catalog_only", "stale_index") for j in journals.values()) else "failed",
        "queries_ok": full_ok, "queries_total": len(JOURNALS),
        "records": records, "errors": failures, "journals": journals}
    out.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"source_status": source_status, "new_candidates": new_items}
