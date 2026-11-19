"""One-off public PDF acceptance gate; never store or publish article content.

shortcut: one fixed relevant article and one independent control PDF; promote
to candidate-driven ingestion only after publisher PDF readback succeeds.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit, parse_qs
from urllib.request import Request, urlopen

TARGET = "https://www.jryj.org.cn/CN/abstract/abstract1663.shtml"
CONTROL = "https://xbzs.ecnu.edu.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=13261"
MAX_HTML = 1_000_000
MAX_PDF = 10_000_000


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.label = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "a":
            self.href = values.get("href")
            self.label = [values.get("title", "")]
        elif tag == "img" and self.href is not None:
            self.label.append(values.get("alt", ""))

    def handle_data(self, text):
        if self.href is not None:
            self.label.append(text)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join(self.label)))
            self.href = None
            self.label = []


def pdf_link(page_url: str, html: bytes) -> str | None:
    parser = Links()
    parser.feed(html.decode("utf-8", errors="replace"))
    host = urlsplit(page_url).hostname
    for href, label in parser.links:
        url = urljoin(page_url, href)
        p = urlsplit(url)
        if p.scheme != "https" or p.hostname != host:
            continue
        path = p.path.lower()
        is_file = path.endswith(".pdf") or "downloadarticlefile" in path
        is_pdf_query = any(x.upper() == "PDF" for x in parse_qs(p.query).get("attachType", []))
        is_labeled = bool(re.search(r"PDF|正文|全文", label, re.I))
        if is_file or is_pdf_query or (is_labeled and re.search(r"download|pdf", path, re.I)):
            return url
    return None


def fetch(url: str, size: int) -> bytes:
    req = Request(url, headers={"User-Agent": "AcademicResearchRadar/0.2 (public PDF availability probe)",
                                "Accept": "application/pdf,text/html;q=0.8,*/*;q=0.2"})
    with urlopen(req, timeout=12) as res:
        # Any redirect must stay on the explicitly approved publisher host.
        final = urlsplit(res.geturl())
        if final.scheme != "https" or final.hostname != urlsplit(url).hostname:
            raise ValueError("cross_origin_redirect_rejected")
        blob = res.read(size + 1)
        if len(blob) > size:
            raise ValueError("payload_over_size_limit")
        return blob


def valid_pdf(blob: bytes) -> bool:
    return (len(blob) >= 1024 and b"%PDF-" in blob[:1024]
            and b"%%EOF" in blob[-2048:])


def inspect_pdf(blob: bytes) -> dict:
    """Inspect in memory; retain metrics only, not article text or PDF."""
    result = {"pdf_sha256": hashlib.sha256(blob).hexdigest(),
              "pdf_bytes": len(blob), "text_extraction": "unavailable"}
    try:
        import pymupdf
    except ImportError:
        return result
    try:
        with pymupdf.open(stream=blob, filetype="pdf") as doc:
            result["page_count"] = len(doc)
            if doc.needs_pass:
                result["text_extraction"] = "encrypted"
                return result
            pages = [page.get_text(sort=True) for page in doc]
        text = "\n".join(pages)
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        result["text_characters"] = len(text)
        result["chinese_characters"] = chinese_chars
        result["text_pages"] = sum(bool(page.strip()) for page in pages)
        result["table_label_hits"] = len(re.findall(r"表\s*[一二三四五六七八九十\d]+", text))
        result["text_extraction"] = "ok" if chinese_chars >= 100 and len(text) >= 500 else "low_confidence"
    except Exception as exc:
        result["text_extraction"] = "failed"
        result["text_error_kind"] = type(exc).__name__
    return result


def probe(name: str, url: str, *, direct: bool = False, reader=fetch, inspector=inspect_pdf) -> dict:
    out = {"name": name, "source_url": url, "pdf_download_verified": False,
           "status": "not_run"}
    try:
        if direct:
            pdf_url = url
        else:
            html = reader(url, MAX_HTML)
            pdf_url = pdf_link(url, html)
            if not pdf_url:
                out["status"] = "pdf_link_not_found"
                return out
        out["pdf_url"] = pdf_url
        blob = reader(pdf_url, MAX_PDF)
        if not valid_pdf(blob):
            out["status"] = "not_a_valid_pdf"
            return out
        out.update(inspector(blob))
        out["pdf_download_verified"] = True
        out["status"] = "downloaded"
    except (OSError, ValueError) as exc:
        out["status"] = "failed"
        out["error_kind"] = type(exc).__name__
        out["error"] = str(exc)[:200]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("pdf-probe-result.json"))
    args = ap.parse_args()
    report = {"gate": "official_pdf_download",
              "target": probe("financial_research_p1a", TARGET),
              "control": probe("unrelated_publisher_open_pdf", CONTROL, direct=True)}
    # The control can show the downloader works, but can never pass the
    # user-requested Financial Research full-text gate.
    report["passed"] = report["target"]["pdf_download_verified"]
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
