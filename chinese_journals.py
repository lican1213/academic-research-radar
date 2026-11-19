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
import socket
import urllib.error
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
    ("finance_economics", "财经研究", "publisher", "https://qks.sufe.edu.cn/J/CJYJ/Article/CurrentIssue/CN"),
    ("financial_research", "金融研究", "publisher", "http://www.jryj.org.cn/CN/1002-7246/current.shtml"),
    ("international_trade", "国际贸易问题", "publisher", "https://gjmw.cbpt.cnki.net/portal/journal/portal/client/paper_list/type_benqi"),
    ("world_economy_studies", "世界经济研究", "publisher", "https://jing.cbpt.cnki.net/portal/journal/portal/client/paper_list/type_benqi"),
)

FALLBACKS = {
    # Mobile NCPSSD issue catalog pages are independent public entry points.
    # They may expose title-only TOC: never infer article-detail coverage.
    "economic_research": ("catalog", "https://m.ncpssd.cn/journal/details?gch=95645X&langType=1&nav=1"),
    "china_industrial": ("catalog", "https://m.ncpssd.cn/journal/details?gch=93800A&langType=1&nav=1"),
    "management_world": ("catalog", "https://m.ncpssd.cn/journal/details?gch=95499X&langType=1&nav=1"),
    "international_trade": ("catalog", "https://ncpssd.org/journal/details?gch=96001X"),
    "world_economy_studies": ("catalog", "https://ncpssd.org/journal/details?gch=91453X"),
    "finance_economics": ("publisher", "https://qks.sufe.edu.cn/J/CJYJ/Article/Latest"),
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
    if (kind == "publisher" and urllib.parse.urlsplit(url).hostname == "www.jryj.org.cn"
            and re.fullmatch(r"/CN/abstract/abstract\d+\.shtml", path, re.I)):
        return True
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


def article_keys(article: dict) -> set[str]:
    """Persist aliases when a known item gains a DOI or stable detail URL."""
    keys = {title_key(article["title"])}
    if article.get("doi"):
        keys.add("doi:" + article["doi"].casefold())
    if article.get("url_scope") != "issue_catalog" and article.get("url"):
        p = urllib.parse.urlsplit(article["url"])
        if p.hostname and p.hostname.endswith("sufe.edu.cn") and "/Article/Details/" in p.path:
            path = re.sub(r"/CN/?$", "", p.path, flags=re.I).rstrip("/")
            keys.add("url:" + p.hostname + path)
        elif p.hostname and (article.get("url_scope") == "article_detail" or ".cbpt.cnki.net" in p.hostname):
            keys.add("url:" + p.hostname + p.path.rstrip("/") + ("?" + p.query if p.query else ""))
    return keys - {""}


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
        # JRYJ has a dedicated publisher current-issue page with official
        # article identifiers; link IDs do not encode the year and issue.
        if (row_issue is None and journal == "金融研究"
                and url == "http://www.jryj.org.cn/CN/1002-7246/current.shtml"
                and re.fullmatch(r"/CN/abstract/abstract\d+\.shtml",
                                 urllib.parse.urlsplit(absolute).path, re.I)):
            row_issue = issue
        if row_issue is None and re.search(r"/Article/(20\d{2})/(\d{1,2})/CN", url, re.I):
            local = re.search(r"/Article/(20\d{2})/(\d{1,2})/CN", url, re.I)
            row_issue = f"{local[1]}-{int(local[2]):02d}"
        if journal == "数量经济技术经济研究" and kind == "publisher":
            # The publisher uses YYYYMMNN file identifiers. Require both
            # explicit row issue and identifier agreement; reject hot/history links.
            number = (urllib.parse.parse_qs(urllib.parse.urlparse(absolute).query).get("file_no") or [""])[0]
            m = re.fullmatch(r"(20\d{2})(0[1-9]|1[0-2])\d{2}", number)
            if not m or row_issue != issue or row_issue != f"{m[1]}-{m[2]}":
                continue
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



class ScanHostBudget:
    """One-scan host circuit: do not retry a known DNS outage nine times.

    A TCP/read timeout may be transient, so only two failures open the
    circuit. The gate is scoped to a scan, never persisted across runs.
    A skipped request raises an OSError and is visible as a failed source.
    """

    def __init__(self) -> None:
        self.timeouts: dict[str, int] = {}
        self.blocked: dict[str, str] = {}

    def fetch(self, url: str, getter, argument):
        host = urllib.parse.urlsplit(url).hostname or ""
        if host in self.blocked:
            raise OSError(f"host_circuit_open: {host}: {self.blocked[host]}")
        try:
            return getter(argument)
        except OSError as error:
            reason = error.reason if isinstance(error, urllib.error.URLError) else error
            if isinstance(reason, socket.gaierror):
                self.blocked[host] = "dns_resolution_failed"
            elif isinstance(reason, TimeoutError):
                self.timeouts[host] = self.timeouts.get(host, 0) + 1
                if self.timeouts[host] >= 2:
                    self.blocked[host] = "repeated_timeout"
            raise



# Stage-2 independent index discovery. Each entry is public and separately
# identified; an index issue is NOT a validated paper list.
# Official finance site is also probed at its canonical apex host, without
# disabling HTTPS certificate or hostname verification.
PRIORITY_SOURCES = {
    "management_world": (
        ("catalog_index", "https://www.cqvip.com/journal/95499X/95499X"),
        ("catalog", "https://m.ncpssd.cn/journal/details?gch=95499X&langType=1&nav=1"),
    ),
    "financial_research": (
        ("publisher", "http://www.jryj.org.cn/CN/1002-7246/home.shtml"),
        ("publisher", "https://jryj.org.cn/CN/1002-7246/current.shtml"),
        ("publisher", "https://www.jryj.org.cn/CN/1002-7246/home.shtml"),
        ("catalog_index", "https://www.cqvip.com/journal/97926X/97926X"),
        ("catalog", "https://m.ncpssd.cn/journal/details?gch=97926X&langType=1&nav=1"),
    ),
}

CQVIP_IDENTITY = {
    "管理世界": ("95499X", "1002-5502"),
    "金融研究": ("97926X", "1002-7246"),
}


def parse_cqvip_issue(payload: bytes, *, journal: str, url: str):
    """Return only a *verified index issue*; never invent article identities.

    Reject unrelated journal pages, an ISSN mismatch, stale year-navigation
    labels and a bare issue number lacking a TOC/issue-item count.
    """
    identity = CQVIP_IDENTITY.get(journal)
    parts = urllib.parse.urlsplit(url)
    if not identity or parts.scheme != "https" or parts.hostname != "www.cqvip.com":
        raise ValueError("untrusted_catalog_index")
    if parts.path != f"/journal/{identity[0]}/{identity[0]}":
        raise ValueError("index_journal_id_mismatch")
    parser = TocHTML()
    parser.feed(payload.decode("utf-8-sig", errors="replace"))
    text = " ".join(" ".join(parser.text_parts).split())
    if journal not in text or not re.search(r"ISSN\s*" + re.escape(identity[1]), text, re.I):
        raise ValueError("index_journal_identity_not_verified")
    # "目录 ... 2026年10期 共：12篇" is distinct from an issue
    # navigation list or a headline stating an issue was released.
    matches = re.findall(
        r"目录\s*(?:封面\s*)?(20\d{2})\s*年\s*(0?[1-9]|1[0-2])\s*期\s*共\s*[:：]\s*(\d{1,3})\s*篇",
        text,
    )
    valid = [(f"{y}-{int(m):02d}", int(n)) for y, m, n in matches if 0 < int(n) <= 100]
    if not valid:
        raise ValueError("index_current_issue_not_verified")
    issue, count = max(valid, key=lambda x: x[0])
    return issue, None, [], count


class PrioritySourceUnavailable(OSError):
    """Retain each attempted source's true failure when all routes fail."""

    def __init__(self, attempts):
        self.attempts = attempts
        super().__init__("priority_sources_unavailable: " + "; ".join(
            f"{x['status']}:{x['url']}" for x in attempts))


def resolve_priority_sources(slug: str, journal: str, kind: str, url: str,
                             previous_issue: str | None, get, sources):
    """Select evidence across fixed trusted sources, never a date inferred from crawl.

    Keep the primary stale response as negative evidence if no viable
    alternative exists. Alternative failures are visible in the snapshot.
    """
    original_url = url
    best = None
    stale = None
    attempts = []
    for source_kind, source_url in ((kind, url), *sources):
        try:
            payload = get(source_url)
            if source_kind == "catalog_index":
                issue, date, papers, indexed_count = parse_cqvip_issue(
                    payload, journal=journal, url=source_url)
                source_kind_output = "catalog"
            else:
                issue, date, papers = parse_toc(
                    payload, journal=journal, kind=source_kind, url=source_url)
                indexed_count = None
                source_kind_output = source_kind
            if not issue:
                raise ValueError("journal_or_issue_not_recognized")
            if previous_issue and issue < previous_issue:
                attempts.append({"url": source_url, "status": "stale_index", "issue": issue})
                if stale is None:
                    stale = (source_kind_output, source_url, issue, date, papers, indexed_count)
                continue
            attempts.append({"url": source_url, "status": "verified_issue_only" if not papers else "parsed_rows",
                             "issue": issue, "row_count": len(papers)})
            candidate = (source_kind_output, source_url, issue, date, papers, indexed_count)
            if (best is None or issue > best[2]
                    or (issue == best[2] and len(papers) > len(best[4]))):
                best = candidate
            # Current publisher articles are a stronger source than an index
            # with the same/older issue; avoid unnecessary additional requests.
            if source_kind == "publisher" and papers:
                break
        except (OSError, ValueError, UnicodeError) as error:
            attempts.append({"url": source_url, "status": "failed",
                             "error": f"{type(error).__name__}: {str(error)[:140]}"})
    if best is None:
        if stale is None:
            raise PrioritySourceUnavailable(attempts)
        best = stale
    output_kind, output_url, issue, date, papers, indexed_count = best
    metadata = {"source_attempts": attempts, "primary_url": original_url}
    if indexed_count is not None:
        metadata["index_claimed_paper_count"] = indexed_count
    if output_url != original_url:
        metadata["recovered_via_alternate"] = True
    return output_kind, output_url, issue, date, papers, metadata


def scan_chinese_journals(out: Path, now: datetime, get=fetch_html, rss_get=None, ncpssd_get=None, priority_sources=None) -> dict:
    """Monitor each journal independently; never infer publication from first_seen."""
    live_mode = get is fetch_html
    if priority_sources is None:
        priority_sources = PRIORITY_SOURCES if live_mode else {}
    if rss_get is None and get is fetch_html:
        rss_get = fetch_rss
    if ncpssd_get is None and get is fetch_html:
        ncpssd_get = fetch_ncpssd
    # Only wrap real network adapters. Injected fixture adapters remain exact,
    # deterministic and untouched; each scheduled process probes anew.
    if get is fetch_html:
        budget = ScanHostBudget()
        real_get = get
        get = lambda url: budget.fetch(url, real_get, url)
        if rss_get is fetch_rss:
            real_rss_get = rss_get
            rss_get = lambda code: budget.fetch(
                f"https://navi.cnki.net/knavi/rss/{code}", real_rss_get, code)
        if ncpssd_get is fetch_ncpssd:
            real_ncpssd_get = ncpssd_get
            ncpssd_get = lambda query: budget.fetch(
                NCPSSD_API, real_ncpssd_get, query)
    seen_path = out / "chinese_seen.json"
    seen = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {}
    if not isinstance(seen, dict):
        raise ValueError("chinese_seen.json must be an object")
    # Old index-path regex wrote an empty key; remove only that invalid sentinel.
    updated = {slug: {**value, "articles": [k for k in value.get("articles", []) if k]} for slug, value in seen.items()}
    seen = updated.copy()
    journals: dict[str, dict] = {}
    new_items: list[dict] = []
    historical_backfill_leads: list[dict] = []
    full_ok = 0  # response with usable rows, not verified article-link coverage
    records = 0
    failures = []
    checked = now.date().isoformat()
    for slug, journal, kind, url in JOURNALS:
        info = {"journal": journal, "source_kind": kind, "url": url, "checked_at": now.isoformat(),
                "status": "not_run", "issue": None, "issue_date": None, "article_count": 0}
        previous = seen.get(slug, {})
        # Last known good issue is only a diagnostic, not a claim about
        # today's live coverage or publication date.
        info["last_known_issue"] = previous.get("issue")
        info["article_snapshot"] = []
        try:
            if slug in priority_sources:
                kind, url, issue, issue_date, articles, provenance = resolve_priority_sources(
                    slug, journal, kind, url, previous.get("issue"), get, priority_sources[slug])
                info.update(provenance)
                info["url"] = url
                info["source_kind"] = kind
            else:
                try:
                    payload = get(url)
                    # A reachable homepage can still contain no usable current rows.
                    if slug == "quant_economics" and not parse_toc(payload, journal=journal, kind=kind, url=url)[2]:
                        raise ValueError("no_verified_current_issue_rows")
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
                # A reachable but regressed catalog is also a source failure.
                # Probe the independent public fallback before labelling it stale.
                if (issue and previous.get("issue") and issue < previous["issue"]
                        and slug in FALLBACKS and url != FALLBACKS[slug][1]):
                    fallback_kind, fallback_url = FALLBACKS[slug]
                    try:
                        fallback_payload = get(fallback_url)
                        candidate_issue, candidate_date, candidate_articles = parse_toc(
                            fallback_payload, journal=journal, kind=fallback_kind, url=fallback_url)
                        if candidate_issue and candidate_issue >= previous["issue"]:
                            info["primary_url"] = url
                            info["primary_failure"] = "stale_primary_index: " + issue
                            info["url"] = url = fallback_url
                            info["source_kind"] = kind = fallback_kind
                            issue, issue_date, articles = candidate_issue, candidate_date, candidate_articles
                    except (OSError, ValueError) as fallback_error:
                        info["fallback_failure"] = f"{type(fallback_error).__name__}: {str(fallback_error)[:140]}"
    
            if not issue:
                info.update(status="unverified", reason="journal_or_issue_not_recognized")
            elif previous.get("issue") and issue < previous["issue"]:
                info.update(status="stale_index", issue=issue, reason="catalog_regressed")
            else:
                metadata_count = sum(a.get("url_scope") == "issue_catalog" for a in articles)
                issue_matches = sum(a.get("issue") == issue for a in articles)
                info["article_snapshot"] = [
                    {**a, "published_at": None, "date_verified": False,
                     "link_verified": False,
                     "role": "current_issue" if a.get("issue") == issue else "historical_or_unbound"}
                    for a in articles]
                info.update(issue=issue, issue_date=issue_date, article_count=len(articles),
                            article_link_count=len(articles)-metadata_count, issue_metadata_count=issue_matches,
                            coverage_kind="issue_metadata" if metadata_count else "issue_bound_links" if articles and issue_matches == len(articles) else "mixed_or_unbound_links" if articles else "issue_only",
                            status="toc_metadata" if metadata_count else "ok" if articles and issue_matches == len(articles) else "mixed_links" if articles else "catalog_only")
                if not articles:
                    info["reason"] = "issue_visible_but_articles_not_verified"
                if info.get("primary_failure"):
                    failure_class = ("stale_primary_index" if info["primary_failure"].startswith("stale_primary_index:")
                                     else "publisher_unavailable" if kind == "catalog" and slug in
                                     ("quant_economics", "financial_research") else "primary_source_unavailable")
                    info["reason"] = failure_class + "; " + info.get("reason", "catalog_fallback")
                if info.get("source_attempts") and any(a["status"] != "parsed_rows" for a in info["source_attempts"]):
                    info["source_quality_note"] = "alternate_source_used_or_primary_degraded"
                if info["status"] == "mixed_links":
                    info["reason"] = "; ".join(filter(None, (info.get("reason"), "mixed_or_unbound_links")))
                previous_articles = set(previous.get("articles", []))
                current = set(previous_articles)
                for article in articles:
                    key = title_key(article["title"])
                    recent_listing = bool(article.get("toc_online_at") and
                                          now.date() - timedelta(days=14) <=
                                          datetime.fromisoformat(article["toc_online_at"]).date() <= now.date())
                    # Mixed homepage links are retained as audit evidence, not
                    # consumed in the normal seen ledger or incremental queue.
                    # A dedicated current-issue page with a recent listing may
                    # provide a lead even when the row omits a repeated issue.
                    if article.get("issue") != issue and not (
                            article.get("issue") is None and recent_listing and "/Article/CurrentIssue/" in url):
                        continue
                    keys = article_keys(article)
                    if not keys:
                        continue
                    already_seen = bool(keys & current)
                    current.update(keys)
                    if already_seen:
                        continue
                    # An issue-only index can seed the *issue* without having
                    # ever observed a single article. When a genuine issue-
                    # bound detail page becomes available later, deliver it
                    # once as a historical backfill, never as a dated new paper.
                    recovered_first_article = bool(
                        previous.get("baselined") and not previous_articles
                        and previous.get("issue") == issue
                        and previous.get("last_article_issue") != issue
                        and article.get("url_scope") == "article_detail")
                    if recovered_first_article:
                        # Preserve the old contract: index-only recovery is NOT
                        # a new-publication event. Surface separately for
                        # human-reviewed historical bibliographic backfill.
                        historical_backfill_leads.append({
                            "title": article["title"], "url": article["url"],
                            "journal": journal, "issue": article.get("issue"),
                            "source": "chinese_journal_toc",
                            "event_type": "issue_backfill",
                            "first_observed_at": checked,
                            "published_at": None, "date_verified": False,
                            "url_scope": article.get("url_scope", "article_detail"),
                        })
                    elif (previous.get("baselined") and (previous_articles or (previous.get("issue") and issue > previous["issue"]) or article.get("url_scope") == "issue_catalog")) or recent_listing:
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
                updated[slug] = {**previous, "issue": issue, "articles": sorted(current), "baselined": True,
                                 "last_issue_observed_at": now.isoformat(),
                                 "rss_baselined": previous.get("rss_baselined", False)}
                if issue_matches:
                    updated[slug]["last_success_at"] = now.isoformat()
                    updated[slug]["last_article_issue"] = issue
                if articles:
                    full_ok += 1
                    records += len(articles)
        except (OSError, ValueError, UnicodeError) as error:
            info.update(status="failed", reason=f"{type(error).__name__}: {str(error)[:120]}")
            if isinstance(error, PrioritySourceUnavailable):
                info["source_attempts"] = error.attempts
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
                if info["status"] not in ("ok", "toc_metadata", "mixed_links"):
                    info["toc_status"] = info["status"]
                    info["status"] = "rss_only"
                    full_ok += 1
                    records += len(rss_articles)
            except (OSError, ValueError, ET.ParseError) as error:
                info["rss"].update(reason=f"{type(error).__name__}: {str(error)[:120]}")
                if updated.get(slug) and previous.get("rss_baselined"):
                    updated[slug]["rss_baselined"] = True
        if info["status"] != "ok":
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
                    keys = article_keys(article)
                    if not keys:
                        continue
                    already_seen = bool(keys & current)
                    current.update(keys)
                    updated[slug] = {**prior, "articles": sorted(current)}
                    if already_seen:
                        continue
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
    if index_status["status"] not in ("ok", "not_run"):
        failures.append(f"NCPSSD topic index: {index_status['status']} ({index_status['queries_ok']}/{index_status['queries_total']})")
    article_level_ok = sum(j["status"] == "ok" for j in journals.values())
    rss_failed = [j["journal"] for j in journals.values()
                  if j.get("rss", {}).get("status") == "failed"]
    # A broken *optional* CNKI RSS must not erase independently verified
    # publisher article links; its health stays visible as a separate field.
    source_status = {"status": "ok" if article_level_ok == len(JOURNALS) and not failures else "degraded" if any(
        j["status"] in ("ok", "toc_metadata", "mixed_links", "rss_only", "catalog_only", "stale_index") for j in journals.values()) else "failed",
        "queries_ok": full_ok, "queries_total": len(JOURNALS),
        "article_level_ok": article_level_ok,
        "article_level_total": len(JOURNALS),
        "rss_health": "degraded" if rss_failed else "ok" if rss_get is not None else "not_run",
        "rss_failed_journals": rss_failed,
        "records": records, "errors": failures, "journals": journals, "ncpssd_topic_index": index_status}
    out.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"source_status": source_status, "new_candidates": new_items,
            "historical_backfill_leads": historical_backfill_leads}
