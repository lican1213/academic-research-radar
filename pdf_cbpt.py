"""Read-only, on-demand CNKI journal-portal PDF probe for two named papers.

No credentials, paywall bypass, guessed download IDs, schedules, or repo PDF storage.
Only a publisher-discovered, anonymously retrievable PDF can enter the ZIP.
"""
from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import Request, urlopen
from zipfile import ZipFile, ZIP_DEFLATED

from pdf_probe import inspect_pdf, valid_pdf

PUBLISHER = "jing.cbpt.cnki.net"
ALLOWED_PDF_HOSTS = frozenset({PUBLISHER, "a.cnki.net"})
MAX_HTML = 2_000_000
MAX_PDF = 20_000_000
TARGETS = (
    {
        "key": "WES_2026_11_006",
        "title": "目的国地缘政治风险下中国企业跨国供应关系调整研究",
        "doi": "10.13516/j.cnki.wes.2026.11.006",
        "article_url": "https://jing.cbpt.cnki.net/portal/journal/portal/client/paper/ea25a14aef4547e4e652de28ccdb4d03",
        "pages_printed": "18-32+135",
    },
    {
        "key": "WES_2026_11_002",
        "title": "对外直接投资如何影响企业出口：来自中国上市公司的差异化证据",
        "doi": "10.13516/j.cnki.wes.2026.11.002",
        "article_url": "https://jing.cbpt.cnki.net/portal/journal/portal/client/paper/658a7489402698caf368e30f134c1156",
        "pages_printed": "3-17+135",
    },
)


def article_allowed(url: str) -> bool:
    p = urlsplit(url)
    return (p.scheme == "https" and p.hostname == PUBLISHER
            and p.port in (None, 443) and not p.username and not p.password
            and not p.query and not p.fragment
            and bool(re.fullmatch(r"/portal/journal/portal/client/paper/[a-f0-9]{32}", p.path)))


def pdf_allowed(url: str) -> bool:
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname not in ALLOWED_PDF_HOSTS
            or p.port not in (None, 443) or p.username or p.password
            or p.fragment):
        return False
    path = p.path.lower()
    if p.hostname == "a.cnki.net":
        return bool(re.fullmatch(r"/gw/api/get/pdf/[a-z0-9/_%-]+\.pdf", path))
    return (path.endswith(".pdf") or
            (path.endswith("/downloadarticlefile.do")
             and parse_qs(p.query).get("attachType") == ["PDF"]))


def fetch_public(url: str, limit: int) -> bytes:
    is_article = article_allowed(url)
    if not (is_article or pdf_allowed(url)):
        raise ValueError("unapproved_url")
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; AcademicResearchRadar-PdfEvidence/1.0)",
        "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.5",
    })
    with urlopen(request, timeout=25) as response:
        final_url = response.geturl()
        # No silent login/authorization redirect or cross-origin fetch.
        if final_url != url:
            raise ValueError("redirect_not_whitelisted")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("response_too_large")
    return data


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        for key in ("href", "src", "data", "data-url", "data-pdf"):
            if d.get(key):
                self.links.append(d[key] or "")
        if tag == "meta" and (d.get("name") or "").lower() == "citation_pdf_url":
            if d.get("content"):
                self.links.append(d["content"] or "")


def normalize_title(title: str) -> str:
    return re.sub(r"[^一-龥a-zA-Z0-9]", "", title).lower()


def find_explicit_pdfs(article_url: str, html_bytes: bytes) -> list[str]:
    """Extract links actually found in HTML or embedded JS, never synthesize IDs."""
    raw = html.unescape(html_bytes.decode("utf-8", errors="replace")).replace("\\/", "/")
    parser = LinkParser()
    parser.feed(raw)
    # A literal PDF URL may be embedded in an SPA state object.
    candidates = parser.links + re.findall(
        r"""https?://[^"'<>\\\s]+|/(?:CN/article/downloadArticleFile\.do|gw/api/get/pdf/)[^"'<>\\\s]+""",
        raw, flags=re.I)
    found = []
    for candidate in candidates:
        url = urljoin(article_url, html.unescape(candidate).rstrip(");,"))
        if pdf_allowed(url) and url not in found:
            found.append(url)
    return found


def browser_discover(article_url: str) -> tuple[list[str], dict]:
    """Anonymous normal-browser rendering; no login, CAPTCHA solution or cookies."""
    diagnostics: dict = {"attempted": True, "engine": "playwright_chromium"}
    links: list[str] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return links, diagnostics | {"error": "playwright_not_installed"}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            def collect(response):
                if pdf_allowed(response.url) and response.url not in links:
                    links.append(response.url)
            page.on("response", collect)
            page.goto(article_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1600)
            initial = page.content().encode("utf-8")
            links.extend(u for u in find_explicit_pdfs(article_url, initial) if u not in links)
            diagnostics["initial_pdf_links"] = len(links)
            diagnostics["title_visible"] = "世界经济研究" in page.content()
            diagnostics["fulltext_cnki_prompt"] = "如需获取全文，请访问cnki.net" in page.content()
            # Observe ordinary UI behavior; never navigate authenticated sessions.
            for phrase in ("PDF", "下载本文"):
                try:
                    element = page.get_by_text(phrase, exact=True).first
                    if element.count():
                        element.click(timeout=2500)
                        page.wait_for_timeout(1300)
                        links.extend(u for u in find_explicit_pdfs(
                            article_url, page.content().encode("utf-8")) if u not in links)
                except Exception as exc:
                    diagnostics["ui_" + ("pdf" if phrase == "PDF" else "download")] = type(exc).__name__
            diagnostics["final_url"] = urlsplit(page.url).hostname
            diagnostics["found_pdf_links"] = len(links)
            browser.close()
    except Exception as exc:
        diagnostics["error"] = type(exc).__name__ + ": " + str(exc)[:120]
    return links, diagnostics


def validate_document(data: bytes, title: str, inspector=inspect_pdf) -> dict:
    if not valid_pdf(data):
        return {"verified": False, "reason": "invalid_pdf_bytes"}
    evidence = inspector(data, title)
    pages = evidence.get("page_count")
    passed = bool(evidence.get("title_match") is True
                  and evidence.get("text_extraction") == "ok"
                  and isinstance(pages, int) and 2 <= pages <= 100)
    return {"verified": passed,
            "reason": "verified" if passed else "pdf_identity_or_text_unverified",
            **evidence}


def probe_target(spec: dict, *, fetcher=fetch_public, browser=browser_discover,
                 inspector=inspect_pdf) -> tuple[dict, bytes | None]:
    outcome = {k: spec[k] for k in ("key", "title", "doi", "article_url", "pages_printed")}
    outcome["status"] = "not_run"
    content: bytes | None = None
    urls: list[str] = []
    try:
        page = fetcher(spec["article_url"], MAX_HTML)
        text = html.unescape(page.decode("utf-8", errors="replace"))
        outcome["article_title_seen"] = normalize_title(spec["title"])[:12] in normalize_title(text)
        outcome["fulltext_cnki_prompt"] = "如需获取全文，请访问cnki.net" in text
        if not outcome["article_title_seen"]:
            outcome["status"] = "article_title_missing"
            return outcome, None
        urls = find_explicit_pdfs(spec["article_url"], page)
    except Exception as exc:
        outcome["static_error"] = type(exc).__name__ + ": " + str(exc)[:120]

    if not urls:
        browser_urls, diagnostics = browser(spec["article_url"])
        outcome["browser"] = diagnostics
        urls = browser_urls

    outcome["discovered_pdf_links"] = len(urls)
    if not urls:
        outcome["status"] = "no_anonymous_pdf_link_found"
        return outcome, None
    attempts = []
    for url in urls[:6]:
        if not pdf_allowed(url):
            attempts.append({"status": "rejected_untrusted_url"})
            continue
        try:
            data = fetcher(url, MAX_PDF)
            v = validate_document(data, spec["title"], inspector=inspector)
            attempts.append({"url": url, "status": v["reason"]})
            if v["verified"]:
                outcome.update(v)
                outcome["pdf_url"] = url
                outcome["status"] = "verified_full_pdf"
                content = data
                break
        except Exception as exc:
            attempts.append({"url": url, "status": type(exc).__name__,
                             "error": str(exc)[:100]})
    outcome["download_attempts"] = attempts
    if content is None:
        outcome["status"] = "pdf_not_verified"
    return outcome, content


def run(out: Path, zip_out: Path, *, fetcher=fetch_public,
        browser=browser_discover, inspector=inspect_pdf) -> dict:
    items = []
    documents: dict[str, bytes] = {}
    for spec in TARGETS:
        row, data = probe_target(spec, fetcher=fetcher, browser=browser,
                                 inspector=inspector)
        items.append(row)
        if data is not None:
            documents[spec["key"]] = data
    passed = len(documents) == len(TARGETS) and all(
        row["status"] == "verified_full_pdf" for row in items)
    report = {"gate": "wes_2026_11_2_original_pdf_delivery",
              "passed": passed, "verified_count": len(documents),
              "target_count": len(TARGETS), "results": items,
              "notes": "No authorized login; fulltext PDF bytes never committed to Git"}
    if passed:
        with ZipFile(zip_out, "w", compression=ZIP_DEFLATED) as z:
            for spec in TARGETS:
                z.writestr(spec["key"] + ".pdf", documents[spec["key"]])
        report["delivery_zip"] = zip_out.name
        report["delivery_zip_bytes"] = zip_out.stat().st_size
        report["delivery_zip_sha256"] = hashlib.sha256(zip_out.read_bytes()).hexdigest()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("wes-pdf-evidence.json"))
    parser.add_argument("--zip-out", type=Path, default=Path("WES_2026_11_Two_Papers.zip"))
    args = parser.parse_args()
    report = run(args.out, args.zip_out)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
