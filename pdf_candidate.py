"""Opt-in, manifest-driven PDF evidence pilot; never part of scheduled metadata scans.

Proves new article discovery and PDF readback across independently verified
publisher hosts. Does not create full-text bibliographies or publish PDFs.
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

from pdf_probe import fetch, inspect_pdf, valid_pdf, MAX_HTML, MAX_PDF

# Deliberately narrow until each new publisher has an actual production readback.
APPROVED_PUBLISHERS = frozenset({
    "qks.sufe.edu.cn",
    "qks.shufe.edu.cn",
    "wjgl.sufe.edu.cn",
    "sjjj.magtech.com.cn",
    "xbzs.ecnu.edu.cn",
})
MAX_CANDIDATES = 5


class PublicLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.anchor = None
        self.label = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "meta" and fields.get("name", "").lower() == "citation_pdf_url":
            if fields.get("content"):
                self.urls.append((fields["content"], "citation_pdf_url"))
        for attr in ("href", "src", "data", "data-pdf", "data-url"):
            if fields.get(attr):
                self.urls.append((fields[attr], ""))
        if tag == "a":
            self.anchor = fields.get("href")
            self.label = []

    def handle_data(self, data):
        if self.anchor:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor:
            self.urls.append((self.anchor, " ".join(self.label)))
            self.anchor = None
            self.label = []


def normalized(text: str) -> str:
    return re.sub(r"[^一-龥A-Za-z0-9]", "", text or "").lower()


def approved_url(url: str, publisher: str) -> bool:
    p = urlsplit(url)
    return (p.scheme == "https" and p.hostname == publisher
            and p.port in (None, 443) and not p.username and not p.password
            and publisher in APPROVED_PUBLISHERS)


def pdf_url(url: str, publisher: str) -> bool:
    if not approved_url(url, publisher):
        return False
    p = urlsplit(url)
    path = p.path.lower()
    if path.endswith(".pdf") or "/pdffulldown/" in path or re.fullmatch(r"/cn/pdf/\d+", path):
        return True
    if path.endswith("/downloadarticlefile.do"):
        return parse_qs(p.query).get("attachType") == ["PDF"]
    return False


def find_pdf_url(article_url: str, page: bytes) -> str | None:
    """Discover only explicit PDF URLs on the real publisher page.

    Handles anchor/iframe/data attributes, as well as the Magtech-style
    direct URL embedded in script. Never guesses PDF IDs.
    """
    publisher = urlsplit(article_url).hostname
    content = html.unescape(page.decode("utf-8", errors="replace"))
    parser = PublicLinks()
    parser.feed(content)
    # Extract literal URLs which are present in a JS field (not guessed).
    embedded = re.findall(
        r"""(?:https?://[A-Za-z0-9.-]+)?/(?:CN/article/downloadArticleFile\.do|J/PDFFullDown/)[^"'<>\s;]+|https?://[A-Za-z0-9.-]+/[^"'<>\s;]+\.pdf(?:\?[^"'<>\s;]+)?""",
        content, flags=re.I)
    for candidate, _label in parser.urls + [(item, "") for item in embedded]:
        url = urljoin(article_url, candidate.strip().rstrip(");"))
        if pdf_url(url, publisher):
            return url
    return None


def verify_candidate(spec: dict, reader=fetch, inspector=inspect_pdf) -> dict:
    result = {"key": spec["key"], "journal": spec["journal"],
              "title": spec["title"], "article_url": spec["article_url"],
              "pdf_verified": False, "text_verified": False,
              "table_verified": False, "status": "not_run"}
    page_url = spec["article_url"]
    host = urlsplit(page_url).hostname
    permitted_hosts = {host} | set(spec.get("approved_pdf_hosts", []))
    if not permitted_hosts.issubset(APPROVED_PUBLISHERS):
        result["status"] = "unapproved_pdf_publisher"
        return result
    if not approved_url(page_url, host):
        result["status"] = "unapproved_article_url"
        return result
    actual = None
    try:
        page = reader(page_url, MAX_HTML)
        page_title_found = normalized(spec["title"])[:12] in normalized(
            html.unescape(page.decode("utf-8", errors="replace")))
        result["article_title_on_page"] = page_title_found
        if not page_title_found:
            result["status"] = "article_title_mismatch"
            return result
        actual = find_pdf_url(page_url, page)
        result["link_source"] = "publisher_article_html" if actual else "none"
    except (OSError, ValueError) as e:
        result["article_page_error"] = type(e).__name__
    if not actual:
        # A PDF URL may be supplied only if an individual official PDF
        # page/URL was independently verified when authoring the manifest.
        actual = spec.get("verified_pdf_url")
        if actual:
            result["link_source"] = "independently_verified_publisher_pdf"
    if not actual:
        result["status"] = "pdf_url_not_found"
        return result
    pdf_host = urlsplit(actual).hostname
    if pdf_host not in permitted_hosts or not pdf_url(actual, pdf_host):
        result["status"] = "unapproved_pdf_url"
        return result
    result["pdf_url"] = actual
    try:
        blob = reader(actual, MAX_PDF)
        if not valid_pdf(blob):
            result["status"] = "invalid_pdf_bytes"
            return result
        fields = inspector(blob, spec["title"])
        result.update(fields)
        result["pdf_verified"] = True
        title_ok = fields.get("title_match") is True
        text_ok = fields.get("text_extraction") == "ok"
        pages = fields.get("page_count")
        result["page_count_plausible"] = isinstance(pages, int) and 2 <= pages <= 200
        expected = spec.get("expected_pages")
        result["page_count_match"] = expected is None or pages == expected
        result["text_verified"] = bool(title_ok and text_ok and
                                       result["page_count_plausible"] and
                                       result["page_count_match"])
        result["status"] = "verified_full_pdf" if result["text_verified"] else "pdf_content_unverified"
    except (OSError, ValueError) as e:
        result["status"] = "download_failed"
        result["error_kind"] = type(e).__name__
        result["error"] = str(e)[:150]
    return result


def evaluate(specs: list[dict], *, reader=fetch, inspector=inspect_pdf) -> dict:
    if not 1 <= len(specs) <= MAX_CANDIDATES:
        raise ValueError("candidate_count_out_of_bounds")
    keys = [s["key"] for s in specs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate_candidate_keys")
    rows = [verify_candidate(s, reader=reader, inspector=inspector) for s in specs]
    mandatory = [r for r, s in zip(rows, specs) if s.get("required")]
    passed = (len(mandatory) >= 2 and
              all(r["text_verified"] for r in mandatory) and
              len({urlsplit(r["article_url"]).hostname for r in mandatory}) >= 2)
    return {
        "gate": "cross_publisher_new_article_pdf_readback",
        "passed": passed,
        "required_count": len(mandatory),
        "verified_count": sum(r["text_verified"] for r in rows),
        "article_count": len(rows),
        "results": rows,
        "notes": "PDF extraction is not table-level empirical verification; no PDF bytes stored",
    }


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--manifest", type=Path, default=Path("tests/pdf_pilot_manifest.json"))
    cli.add_argument("--out", type=Path, default=Path("pdf-candidate-evidence.json"))
    args = cli.parse_args()
    specs = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = evaluate(specs)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
