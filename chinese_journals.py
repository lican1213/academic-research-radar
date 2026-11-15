"""Public table-of-contents monitor for priority Chinese economics journals.

This is a conservative discovery aid, NOT publication-date verification.
Publisher pages are preferred where available; NCPS SD is an authoritative
catalog fallback, not the journal publisher. No login/paywall bypass.
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
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
    ("economic_research", "经济研究", "catalog", "https://ncpssd.org/journal/details.aspx?gch=95645X"),
    ("china_industrial", "中国工业经济", "catalog", "https://ncpssd.org/journal/details.aspx?gch=93800A"),
    ("management_world", "管理世界", "catalog", "https://ncpssd.org/journal/details?gch=95499X&langType=1"),
    ("world_economy", "世界经济", "publisher", "https://sjjj.magtech.com.cn/CN/home"),
    ("quant_economics", "数量经济技术经济研究", "publisher", "https://www.jqte.net/sljjjsjjyj/ch/index.aspx"),
    ("finance_economics", "财经研究", "publisher", "https://qks.sufe.edu.cn/J/CJYJ/Article/Latest"),
    ("financial_research", "金融研究", "publisher", "https://www.jryj.org.cn/CN/1002-7246/current.shtml"),
    ("international_trade", "国际贸易问题", "publisher", "https://gjmw.cbpt.cnki.net/portal/journal/portal/client/paper_list/type_benqi"),
    ("world_economy_studies", "世界经济研究", "publisher", "https://jing.cbpt.cnki.net/portal/journal/portal/client/paper_list/type_benqi"),
)

FALLBACKS = {
    "international_trade": ("catalog", "https://ncpssd.org/journal/details?gch=96001X"),
    "world_economy_studies": ("catalog", "https://ncpssd.org/journal/details?gch=91453X"),
    "finance_economics": ("publisher", "https://qks.sufe.edu.cn/J/CJYJ/Article/CurrentIssue/CN"),
    "quant_economics": ("catalog", "https://www.ncpssd.org/journal/details?gch=94503X"),
    "financial_research": ("catalog", "https://m.ncpssd.cn/journal/details?gch=97926X&langType=1&nav=1"),
}

ONLINE_RE = re.compile(r"在线出版日期\s*[:：]\s*(20\d{2})年(\d{1,2})月(\d{1,2})日")
DOI_RE = re.compile(r"10\.\d{4,9}/[A-Za-z0-9._;()/:+-]+", re.I)

ISSUE_RE = re.compile(r"(20\d{2})\s*年[^\n]{0,40}?(?:第\s*)?(0?[1-9]|1[0-2])\s*期")
QUANT_ISSUE_RE = re.compile(r"(20\d{2})\s*,\s*\((0?[1-9]|1[0-2])\)\s*:")
DATE_RE = re.compile(r"(?:刊出日期|出版日期)\s*[:：]\s*(20\d{2}-\d{2}-\d{2})")
BAD_TITLES = ("当期目录", "过刊浏览", "摘要点击", "全文下载", "期刊介绍", "下载全文",
              "复现包", "补充材料", "作者在线", "在线投稿", "责任编辑", "目录文件",
              "更多信息", "发表文章", "摘要", "文献中心", "联系我们")


class TocHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str, int]] = []
        self.href: str | None = None
        self.anchor_parts: list[str] = []
        self.anchor_index = 0
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "template"):
            self.hidden_depth += 1
        if self.hidden_depth:
            return
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.anchor_parts = []
            self.anchor_index = len(self.text_parts)

    def handle_data(self, data: str) -> None:
        if self.hidden_depth:
            return
        self.text_parts.append(data)
        if self.href is not None:
            self.anchor_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "template"):
            self.hidden_depth = max(0, self.hidden_depth - 1)
            return
        if self.hidden_depth:
            return
        if tag == "a":
            if self.href:
                self.links.append((" ".join(" ".join(self.anchor_parts).split()), self.href, self.anchor_index))
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
    if re.fullmatch(r"/portal/(?:journal/)?portal/client/paper/[a-f0-9]{32}/?", path, re.I):
        return kind == "publisher"
    if kind == "catalog":
        # National catalog may expose an issue but not verifiable article pages.
        # Do not mistake download links, buttons or site navigation for papers.
        return bool(re.search(r"/(?:article|literature|paper)/[A-Za-z0-9_-]{8,}", path, re.I))
    if "/sljjjsjjyj/ch/reader/view_abstract.aspx" in path.lower():
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        return bool(re.fullmatch(r"20\d{6}", (query.get("file_no") or [""])[0]))
    if re.match(r"/J/(?:CJYJ|j00001)/", path, re.I):
        # SUFE issue links look like /Article/2026/09/CN and must NOT be
        # mistaken for articles. Real detail links use /Article/Details/<id>/CN.
        return bool(re.fullmatch(r"/J/(?:CJYJ|j00001)/Article/Details/[A-Za-z0-9_-]{12,}(?:/CN)?/?", path, re.I))
    return bool(re.search(r"/CN/Y20\d{2}/|/CN/10\.\d{4,9}/", path, re.I))


# A journal issue is a distinct data object, not the homepage or its
# recommended-paper carousel (see cookjohn/cnki-skills, cnki-journal-toc).
ISSUE_HEADER = re.compile(r"^\s*(20\d{2})\s*年\s*(?:第\s*)?(0?[1-9]|1[0-2])\s*期\s*$")
ISSUE_ROW = re.compile(r"(20\d{2})\s*年\s*(?:第\s*)?(0?[1-9]|1[0-2])\s*期(?:\s*No\.\s*\d+)?")
CATALOG_PAGES = re.compile(r"[\(（]\s*(\d{1,4})\s*[-—–－]\s*(\d{1,4})\s*[\)）]")
CATALOG_AUTHORS = re.compile(r"(?:[\u3400-\u9fff·]{1,10}\s*\[\s*\d+(?:[,，]\s*\d+)*\s*\]\s*[;；]?\s*)+")


def title_key(title: str) -> str:
    return re.sub(r"[^\w]", "", title).casefold()


def catalog_issue_rows(parser: TocHTML, *, journal: str, url: str) -> tuple[str | None, list[dict]]:
    """NCPSSD public issue text: title, affiliation-tagged authors, pages.
    No guessed article URLs: the actual issue-level source is retained.
    Reject navigation, abstracts, full-issue/recommendation sections and
    unstructured title-only text; metadata leads still need paper verification.
    """
    host = urllib.parse.urlparse(url).hostname or ""
    if not (host in ("ncpssd.cn", "ncpssd.org") or host.endswith((".ncpssd.cn", ".ncpssd.org"))):
        return None, []
    parts = [" ".join(value.split()) for value in parser.text_parts if value.strip()]
    if journal not in " ".join(parts):
        return None, []
    groups: dict[str, dict[str, dict]] = {}
    # Heading may be split into adjacent text nodes in the rendered DOM.
    active = None
    buffer = []
    for i, part in enumerate(parts):
        if "整刊阅读" in part or any(x in part for x in ("优先发布论文", "相关文献", "推荐文章", "热门文章")):
            active, buffer = None, []
            continue
        match = ISSUE_HEADER.fullmatch(part)
        if match is None and i and not active:
            match = ISSUE_HEADER.fullmatch(parts[i-1] + " " + part)
        if match:
            active = f"{match[1]}-{int(match[2]):02d}"
            buffer = []
            continue
        if not active:
            continue
        buffer.append(part)
        if len(buffer) > 14:
            buffer.pop(0)
        text = "\n".join(buffer)
        pages = CATALOG_PAGES.search(text)
        if not pages:
            continue
        prefix = text[:pages.start()]
        authors = CATALOG_AUTHORS.search(prefix)
        if authors:
            title = prefix[:authors.start()].strip().split("\n")[-1].strip()
            # A title is required immediately before authors, not UI metadata.
            if (6 <= len(title) <= 150 and re.search(r"[\u3400-\u9fff]", title)
                    and not any(x in title for x in BAD_TITLES)
                    and not any(x in title for x in ("征稿启事", "本刊启事", "订阅启事", "整刊阅读"))
                    and 0 < int(pages[1]) <= int(pages[2])):
                key = title_key(title)
                groups.setdefault(active, {})[key] = {"title": title, "url": url,
                    "url_scope": "issue_catalog", "issue": active,
                    "authors": " ".join(authors.group(0).split()).strip(";； "),
                    "pages": f"{pages[1]}-{pages[2]}", "toc_online_at": None, "doi": None}
        buffer = []
    if not groups:
        return None, []
    issue = max(groups)
    return issue, list(groups[issue].values())


def parse_toc(payload: bytes, *, journal: str, kind: str, url: str) -> tuple[str | None, str | None, list[dict]]:
    parser = TocHTML()
    parser.feed(payload.decode("utf-8-sig", errors="replace"))
    text = "\n".join(parser.text_parts)
    if journal not in text:
        return None, None, []
    issues = ISSUE_RE.findall(text)
    cbpt_issue = "/paper_list/type_benqi" in url and ".cbpt.cnki.net" in (urllib.parse.urlparse(url).hostname or "")
    if cbpt_issue:
        first = next((ISSUE_HEADER.fullmatch(p.strip()) for p in parser.text_parts if ISSUE_HEADER.fullmatch(p.strip())), None)
        if first is None:
            first = ISSUE_ROW.search(text)
        issues = [first.groups()] if first else []
    elif ".cbpt.cnki.net" in (urllib.parse.urlparse(url).hostname or ""):
        first = ISSUE_RE.search(text)
        issues = [first.groups()] if first else []
    if journal == "数量经济技术经济研究":
        issues.extend(QUANT_ISSUE_RE.findall(text))
    # Homepage content can contain prior issues; take the latest issue for
    # the year and reject year/month regression later in scan().
    issue = max((f"{y}-{int(m):02d}" for y, m in issues), default=None)
    date_match = DATE_RE.search(text)
    issue_date = date_match.group(1) if date_match else None
    articles: list[dict] = []
    links: list[tuple[str, str, int]] = []
    seen_urls: set[str] = set()
    for title, href, part_index in parser.links:
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
        # Anchor may contain <sup> or other markup; use DOM text-part offsets,
        # not an exact title string search (which drops such legitimate titles).
        seen_urls.add(absolute)
        links.append((title, absolute, part_index))
    links.sort(key=lambda x: x[2])
    for index, (title, absolute, position) in enumerate(links):
        following = links[index + 1][2] if index + 1 < len(links) else len(parser.text_parts)
        section = "\n".join(parser.text_parts[position:min(following, position + 150)])
        published = None
        match = ONLINE_RE.search(section)
        if match:
            y, m, d = map(int, match.groups())
            try:
                published = datetime(y, m, d).date().isoformat()
            except ValueError:
                pass
        doi_match = DOI_RE.search(section) if kind == "publisher" else None
        row_issue = None
        host = urllib.parse.urlparse(url).hostname or ""
        match_path = re.search(r"/CN/Y(20\d{2})/V\d+/I(\d{1,2})/", absolute, re.I)
        if match_path:
            row_issue = f"{match_path[1]}-{int(match_path[2]):02d}"
        else:
            local = ISSUE_RE.search(section.replace("\n", " "))
            if local:
                row_issue = f"{local[1]}-{int(local[2]):02d}"
            elif journal == "数量经济技术经济研究":
                local = QUANT_ISSUE_RE.search(section)
                if local:
                    row_issue = f"{local[1]}-{int(local[2]):02d}"
        if row_issue is None and (".cbpt.cnki.net" in host or "/Article/Latest" in url):
            published = None
            doi_match = None
        # Never inherit the maximum issue of a mixed homepage or latest-articles list.
        if row_issue is None and re.search(r"/Article/(20\d{2})/(\d{1,2})/CN", url, re.I):
            local = re.search(r"/Article/(20\d{2})/(\d{1,2})/CN", url, re.I)
            row_issue = f"{local[1]}-{int(local[2]):02d}"
        if cbpt_issue:
            # Match the explicit per-paper current issue. Historical/top-read links must not pass.
            row = ISSUE_ROW.search(section)
            row_issue = f"{row[1]}-{int(row[2]):02d}" if row else None
            if row_issue != issue or row_issue is None:
                continue
        articles.append({"title": title, "url": absolute, "toc_online_at": published,
                         "issue": row_issue, "url_scope": "article_detail",
                         "doi": doi_match.group(0).rstrip(".,;") if doi_match else None})
    if kind == "catalog" and not articles:
        catalog_issue, rows = catalog_issue_rows(parser, journal=journal, url=url)
        if rows and (issue is None or catalog_issue >= issue):
            return catalog_issue, None, rows
    return issue, issue_date, articles


# Public CNKI subscription feeds; ordinary anonymous session cookies only.
# Design reference: MartyYao/Chinese-Literature-Skill (MIT), cnki-rss.py.
RSS_CODES = {
    "economic_research": "JJYJ", "china_industrial": "GGYY",
    "management_world": "GLSJ", "world_economy": "SJJJ",
    "quant_economics": "SLJY", "finance_economics": "CJYJ",
    "financial_research": "JRYJ", "international_trade": "GJMW",
    "world_economy_studies": "JING",
}


def fetch_rss(code: str) -> bytes:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    headers = {"User-Agent": "AcademicResearchRadar/0.3 (public RSS reader)",
               "Accept": "application/rss+xml,application/xml,text/xml,text/html"}
    for url in (f"https://navi.cnki.net/knavi/journals/{code}/detail?uniplatform=NZKPT",
                f"https://navi.cnki.net/knavi/rss/{code}"):
        with opener.open(urllib.request.Request(url, headers=headers), timeout=12) as response:
            payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("RSS payload too large")
    return payload


def parse_rss(payload: bytes, journal: str) -> list[dict]:
    root = ET.fromstring(payload)
    channel = root.find("channel")
    if channel is None or journal not in (channel.findtext("title") or ""):
        raise ValueError("RSS journal identity not verified")
    result = []
    for entry in channel.findall("item"):
        title = " ".join((entry.findtext("title") or "").split())
        url = (entry.findtext("link") or "").strip()
        host = urllib.parse.urlparse(url).hostname or ""
        path = urllib.parse.urlparse(url).path.lower()
        if not (8 <= len(title) <= 150 and re.search(r"[\u3400-\u9fff]", title)):
            continue
        if any(word in title for word in ("征稿启事", "订阅启事", "本刊启事", "封面", "编辑部公告", "目次")):
            continue
        if urllib.parse.urlparse(url).scheme != "https" or not (host == "cnki.net" or host.endswith(".cnki.net")):
            continue
        if not any(part in path for part in ("detail", "article", "abstract")):
            continue
        feed_date = None
        raw = entry.findtext("pubDate") or ""
        try:
            feed_date = parsedate_to_datetime(raw).date().isoformat()
        except (ValueError, TypeError, OverflowError):
            pass
        result.append({"title": title, "url": url, "rss_event_at": feed_date,
                       "authors": (entry.findtext("author") or "").strip(), "doi": None})
    if not result:
        raise ValueError("RSS returned no verifiable article entries")
    return result


# Public structured search, adapted from the documented anonymous NCPSSD
# search request in MartyYao/Chinese-Literature-Skill (MIT).
NCPSSD_API = "https://www.ncpssd.cn/searchHandler/search"
NCPSSD_TOPICS = ("耐心资本", "专利出海", "协同出海", "供应链韧性", "供应链关系", "对外直接投资", "专利文本", "人工智能")


def fetch_ncpssd(query: str) -> bytes:
    conditions = "(" + " OR ".join(f'{field}="{query}"' for field in ("IKTE", "IKST", "IKET")) + ")"
    data = urllib.parse.urlencode({"search": conditions, "pageNum": "1", "pageSize": "50",
        "sort": "synUpdateType|DESC,date|DESC,ik_subject|DESC,id|DESC", "sType": "0",
        "ajaxKeys": "", "customShowCondition": query}).encode()
    request = urllib.request.Request(NCPSSD_API, data=data, headers={
        "User-Agent": "AcademicResearchRadar/0.4 (public metadata)",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.ncpssd.cn/"})
    with urllib.request.urlopen(request, timeout=12) as response:
        return response.read(2_000_001)


def parse_ncpssd(payload: bytes, journals: set[str]) -> list[dict]:
    doc = json.loads(payload)
    if not isinstance(doc, dict) or doc.get("result") is not True or not isinstance(doc.get("data"), dict):
        raise ValueError("NCPSSD response not successful")
    rows = doc["data"].get("rows")
    if not isinstance(rows, list):
        raise ValueError("NCPSSD rows not verified")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        journal = str(row.get("cbw_name") or "").strip()
        if journal not in journals:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", str(row.get("title") or ""))).strip()
        if not 8 <= len(title) <= 150 or not re.search(r"[\u3400-\u9fff]", title):
            continue
        if any(x in title for x in ("征稿启事", "订阅启事", "本刊启事", "封面", "编辑部公告", "目次")):
            continue
        doi = str(row.get("doi") or "").strip()
        doi = doi if DOI_RE.fullmatch(doi) else None
        url = None
        if doi:
            url = "https://doi.org/" + doi
        else:
            for name in ("HtmlUrl", "encryptedUrl"):
                raw = str(row.get(name) or "").strip()
                candidate = urllib.parse.urljoin("https://www.ncpssd.cn/", raw)
                parts = urllib.parse.urlparse(candidate)
                host = parts.hostname or ""
                if raw and parts.scheme == "https" and (host in ("ncpssd.cn", "ncpssd.org") or host.endswith((".ncpssd.cn", ".ncpssd.org"))) and re.search(r"/(?:article|literature|paper|detail)", parts.path, re.I):
                    url = candidate
                    break
        if not url:
            continue
        year, month = str(row.get("years") or ""), str(row.get("num") or "")
        issue = f"{year}-{int(month):02d}" if re.fullmatch(r"20\d{2}", year) and re.fullmatch(r"0?[1-9]|1[0-2]", month) else None
        event = str(row.get("date") or "")[:10]
        event = event if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", event) else None
        result.append({"title": title, "journal": journal, "url": url, "doi": doi,
            "authors": str(row.get("creator_first") or row.get("creator") or "").strip(),
            "issue": issue, "index_date": event})
    return result


def scan_chinese_journals(out: Path, now: datetime, get=fetch_html, rss_get=None, ncpssd_get=None) -> dict:
    """Monitor each journal independently; never infer publication from first_seen."""
    if rss_get is None and get is fetch_html:
        rss_get = fetch_rss
    if ncpssd_get is None and get is fetch_html:
        ncpssd_get = fetch_ncpssd
    seen_path = out / "chinese_seen.json"
    seen = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {}
    if not isinstance(seen, dict):
        raise ValueError("chinese_seen.json must be an object")
    # Old index-path regex wrote an empty key; remove only that invalid sentinel.
    updated = {slug: {**value, "articles": [k for k in value.get("articles", []) if k]} for slug, value in seen.items()}
    seen = updated.copy()
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
                metadata_count = sum(a.get("url_scope") == "issue_catalog" for a in articles)
                issue_matches = sum(a.get("issue") == issue for a in articles)
                info.update(issue=issue, issue_date=issue_date, article_count=len(articles),
                            article_link_count=len(articles)-metadata_count, issue_metadata_count=issue_matches,
                            coverage_kind="issue_metadata" if metadata_count else "issue_bound_links" if articles and issue_matches == len(articles) else "mixed_or_unbound_links" if articles else "issue_only",
                            status="toc_metadata" if metadata_count else "ok" if articles else "catalog_only")
                if not articles:
                    info["reason"] = "issue_visible_but_articles_not_verified"
                if info.get("primary_failure"):
                    info["reason"] = "publisher_unavailable; " + info.get("reason", "catalog_fallback")
                previous_articles = set(previous.get("articles", []))
                current = set(previous_articles)
                for article in articles:
                    key = title_key(article["title"])
                    doi_key = "doi:" + article["doi"].casefold() if article.get("doi") else None
                    if key in current or (doi_key and doi_key in current):
                        continue
                    current.add(key)
                    if doi_key:
                        current.add(doi_key)
                    recent_listing = bool(article.get("toc_online_at") and
                                          now.date() - timedelta(days=14) <=
                                          datetime.fromisoformat(article["toc_online_at"]).date() <= now.date())
                    if (previous.get("baselined") and (previous_articles or (previous.get("issue") and issue > previous["issue"]) or article.get("url_scope") == "issue_catalog")) or recent_listing:
                        ident = hashlib.sha256((slug + ":" + key).encode()).hexdigest()[:16]
                        new_items.append({
                            "id": "journal:" + slug + ":" + ident,
                            "title": article["title"],
                            "authors": article.get("authors"), "pages": article.get("pages"),
                            "url_scope": article.get("url_scope", "article_detail"),
                            "journal": journal,
                            "url": article["url"],
                            "source": "chinese_journal_toc",
                            "source_kind": kind,
                            "issue": article.get("issue"),
                            "issue_date": issue_date if article.get("issue") == issue else None,
                            "published_at": None,
                            "toc_online_at": article.get("toc_online_at"),
                            "doi": article.get("doi"),
                            "first_observed_at": checked,
                            "event_type": "toc_online_listing" if article.get("toc_online_at") else "issue_backfill" if article.get("issue") and previous.get("issue") and article["issue"] <= previous["issue"] else "first_seen_in_toc",
                            "date_verified": False,
                            "note": "TOC online date may differ from article detail publication date; verify both.",
                        })
                updated[slug] = {"issue": issue, "articles": sorted(current), "baselined": True,
                                 "last_success_at": now.isoformat(), "rss_baselined": previous.get("rss_baselined", False)}
                if articles:
                    full_ok += 1
                    records += len(articles)
        except (OSError, ValueError, UnicodeError) as error:
            info.update(status="failed", reason=f"{type(error).__name__}: {str(error)[:120]}")
        if rss_get is not None and slug in RSS_CODES:
            code = RSS_CODES[slug]
            info["rss"] = {"url": f"https://navi.cnki.net/knavi/rss/{code}", "status": "failed", "article_count": 0}
            try:
                rss_articles = parse_rss(rss_get(code), journal)
                prior = updated.get(slug, previous)
                current = set(prior.get("articles", []))
                rss_baselined = previous.get("rss_baselined", False)
                # A first successful feed establishes the historical baseline. Recent feed events are leads only.
                for article in rss_articles:
                    key = re.sub(r"[^\w]", "", article["title"]).casefold()
                    if key in current:
                        continue
                    current.add(key)
                    event = article["rss_event_at"]
                    recent = bool(event and (now.date() - timedelta(days=14)).isoformat() <= event <= checked)
                    if rss_baselined or recent:
                        ident = hashlib.sha256((slug + ":" + key).encode()).hexdigest()[:16]
                        new_items.append({"id": "journal:" + slug + ":" + ident, **article,
                            "journal": journal, "source": "cnki_rss", "source_kind": "index_feed",
                            "issue": None, "issue_date": None, "published_at": None, "toc_online_at": None,
                            "first_observed_at": checked, "event_type": "rss_listing", "date_verified": False,
                            "note": "RSS event date is not verified first publication date."})
                updated[slug] = {**prior, "articles": sorted(current), "rss_baselined": True}
                info["rss"].update(status="ok", article_count=len(rss_articles), latest_event=max((x["rss_event_at"] for x in rss_articles if x["rss_event_at"]), default=None))
                if info["status"] not in ("ok", "toc_metadata"):
                    info["toc_status"] = info["status"]
                    info["status"] = "rss_only"
                    full_ok += 1
                    records += len(rss_articles)
            except (OSError, ValueError, ET.ParseError) as error:
                info["rss"].update(reason=f"{type(error).__name__}: {str(error)[:120]}")
                if updated.get(slug) and previous.get("rss_baselined"):
                    updated[slug]["rss_baselined"] = True
        if info["status"] != "ok" or info.get("rss", {}).get("status") == "failed":
            failures.append(f"{journal}: {info['status']} ({info.get('reason', '')}); RSS={info.get('rss', {}).get('status', 'not_run')}")
        journals[slug] = info
    # Topic search adds verified-index leads but never counts as a complete issue scan.
    index_status = {"status": "not_run", "queries_ok": 0, "queries_total": len(NCPSSD_TOPICS), "records": 0, "errors": []}
    if ncpssd_get is not None:
        name_to_slug = {name: slug for slug, name, _, _ in JOURNALS}
        for query in NCPSSD_TOPICS:
            try:
                rows = parse_ncpssd(ncpssd_get(query), set(name_to_slug))
                index_status["queries_ok"] += 1
                index_status["records"] += len(rows)
                for article in rows:
                    slug = name_to_slug[article["journal"]]
                    prior = updated.get(slug, {})
                    current = set(prior.get("articles", []))
                    key = title_key(article["title"])
                    doi_key = "doi:" + article["doi"].casefold() if article.get("doi") else None
                    if key in current or (doi_key and doi_key in current):
                        continue
                    current.add(key)
                    if doi_key:
                        current.add(doi_key)
                    updated[slug] = {**prior, "articles": sorted(current)}
                    # Old recovered leads are explicitly backfill, not a new publication.
                    event = article.get("index_date")
                    issue = article.get("issue")
                    if (event and (now.date() - timedelta(days=30)).isoformat() <= event <= checked) or (issue and issue >= (now.date() - timedelta(days=60)).strftime("%Y-%m") and issue <= now.strftime("%Y-%m")):
                        ident = hashlib.sha256((slug + ":" + key).encode()).hexdigest()[:16]
                        new_items.append({"id": "journal:" + slug + ":" + ident, **article,
                            "source": "ncpssd_topic_index", "source_kind": "catalog_index",
                            "published_at": None, "date_verified": False, "first_observed_at": checked,
                            "event_type": "index_backfill", "note": "Indexed lead; verify original publication date and issue."})
            except (OSError, ValueError, TypeError) as error:
                index_status["errors"].append(f"{query}: {type(error).__name__}: {str(error)[:120]}")
        index_status["status"] = "ok" if index_status["queries_ok"] == len(NCPSSD_TOPICS) else "degraded" if index_status["queries_ok"] else "failed"
    source_status = {"status": "ok" if full_ok == len(JOURNALS) and not failures else "degraded" if any(
        j["status"] in ("ok", "toc_metadata", "rss_only", "catalog_only", "stale_index") for j in journals.values()) else "failed",
        "queries_ok": full_ok, "queries_total": len(JOURNALS),
        "records": records, "errors": failures, "journals": journals, "ncpssd_topic_index": index_status}
    out.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"source_status": source_status, "new_candidates": new_items}
