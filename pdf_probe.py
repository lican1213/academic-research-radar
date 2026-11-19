"""One-off public PDF acceptance gate; never store or publish article content.

shortcut: one fixed relevant article and one independent control PDF; promote
to candidate-driven ingestion only after publisher PDF readback succeeds.
"""
from __future__ import annotations

import argparse
import hashlib
import html as html_lib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit, parse_qs
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile

# The journal itself advertises HTTP. Its HTTPS certificate does not match
# www.jryj.org.cn; restrict plaintext access to these publisher paths only.
PUBLISHER = "www.jryj.org.cn"
ARTICLES = (
    (1662, "银行资产负债结构、放贷能力与货币政策传导效果", 19),
    (1663, "地缘政治风险、跨境供应链与中国企业债券信用利差", 19),
    (1664, "中国企业价格加成和劳动收入份额", 19),
    (1665, "贸易冲突下企业提前布局战略性新兴产业的韧性效应", 19),
    (1666, "外贸下乡：自贸试验区农村劳动力增收效应", 18),
    (1667, "股权结构的流动性冲击敞口如何影响债券信用利差", 18),
)
TARGET = "http://www.jryj.org.cn/CN/abstract/abstract1663.shtml"
CONTROL = "https://xbzs.ecnu.edu.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=13261"
MAX_HTML = 1_000_000
MAX_PDF = 10_000_000

# Verified originals from production run 44470870725.
REFERENCE_SHA256 = {
    1662: "65d3f9e1a861e769793b21994d53a5a3fcca23fe367b5531724235fae68eb8ca",
    1663: "7d9123636ba35530ac71e64e047b774febecd1dba5e9d2384cf98e9d1f81b188",
    1664: "d98f0dc2cd3afac71928807a020d8b44270646350cba78cc722c63f6bc9decc2",
    1665: "f4f9dd7749f29452c7a45284116049760335a5d22983d1d01de8b03a98429422",
    1666: "c5f3a104eacbdeeeb316555b76d2a54d561f8bdc524c134bba9d5a333176cd8e",
    1667: "306495e4354cd6e0b6b6235f425da1ba22699268b9268eb84615fb7fa1033b42",
}


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


def approved_url(url: str) -> bool:
    p = urlsplit(url)
    if p.scheme == "https":
        return True
    if p.scheme != "http" or p.hostname != PUBLISHER:
        return False
    if re.fullmatch(r"/CN/abstract/abstract166[2-7]\.shtml", p.path):
        return True
    return (p.path == "/CN/article/downloadArticleFile.do" and
            parse_qs(p.query).get("attachType") == ["PDF"] and
            parse_qs(p.query).get("id", [""])[0] in
            {str(i) for i, _, _ in ARTICLES})


def pdf_link(page_url: str, html: bytes) -> str | None:
    """Read a publisher-provided URL, including script attributes used by Magtech."""
    parser = Links()
    parser.feed(html.decode("utf-8", errors="replace"))
    host = urlsplit(page_url).hostname
    expected = re.search(r"/abstract/abstract(\d+)\.shtml$", urlsplit(page_url).path)
    if not expected:
        return None
    # Some Magtech themes place the real URL in onclick/JS, not <a href>.
    source = html_lib.unescape(html.decode("utf-8", errors="replace"))
    embedded = re.findall(
        r'(?:https?://www\.jryj\.org\.cn)?/CN/article/downloadArticleFile\.do\?[^"\'\s<>]+',
        source)
    for href in [h for h, _ in parser.links] + embedded:
        url = urljoin(page_url, href.rstrip(");"))
        p = urlsplit(url)
        if p.hostname != host or p.scheme != urlsplit(page_url).scheme or not approved_url(url):
            continue
        if p.path != "/CN/article/downloadArticleFile.do":
            continue
        qs = parse_qs(p.query)
        if qs.get("attachType") == ["PDF"] and qs.get("id") == [expected.group(1)]:
            return url
    return None


def fetch(url: str, size: int) -> bytes:
    if not approved_url(url):
        raise ValueError("unapproved_transport_or_path")
    req = Request(url, headers={"User-Agent": "AcademicResearchRadar/0.2 (public PDF availability probe)",
                                "Accept": "application/pdf,text/html;q=0.8,*/*;q=0.2"})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as res:
                # No cross-origin redirect and no TLS verification override.
                final = urlsplit(res.geturl())
                if final.hostname != urlsplit(url).hostname or final.scheme != urlsplit(url).scheme or not approved_url(res.geturl()):
                    raise ValueError("cross_origin_redirect_rejected")
                blob = res.read(size + 1)
                if len(blob) > size:
                    raise ValueError("payload_over_size_limit")
                return blob
        except TimeoutError:
            if attempt == 2:
                raise


def valid_pdf(blob: bytes) -> bool:
    return (len(blob) >= 1024 and b"%PDF-" in blob[:1024]
            and b"%%EOF" in blob[-2048:])


def inspect_pdf(blob: bytes, expected_title: str | None = None) -> dict:
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
        if expected_title:
            normalize = lambda value: re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", value)
            result["title_match"] = normalize(expected_title)[:12] in normalize(text)

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


def write_delivery_zip(path: Path, files: dict[int, bytes],
                       reference: dict[int, str] = REFERENCE_SHA256) -> None:
    """Only write a complete set of known, previously verified PDF originals."""
    if set(files) != {item[0] for item in ARTICLES}:
        raise ValueError("incomplete_six_paper_set")
    for article_id, blob in files.items():
        if not valid_pdf(blob) or hashlib.sha256(blob).hexdigest() != reference[article_id]:
            raise ValueError(f"pdf_identity_mismatch_{article_id}")
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as bundle:
        for article_id, title, _ in ARTICLES:
            bundle.writestr(f"{article_id}_{title}.pdf", files[article_id])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("pdf-probe-result.json"))
    ap.add_argument("--zip-out", type=Path, default=None,
                    help="Temporarily deliver the six verified originals; no Git commit")
    args = ap.parse_args()
    targets = []
    saved_pdfs: dict[int, bytes] = {}

    def capture_pdf(blob: bytes, article_id: int, title: str) -> dict:
        metrics = inspect_pdf(blob, title)
        saved_pdfs[article_id] = blob
        return metrics

    for article_id, title, expected_pages in ARTICLES:
        url = f"http://{PUBLISHER}/CN/abstract/abstract{article_id}.shtml"
        result = probe("financial_research_" + str(article_id), url,
                       inspector=lambda blob, article_id=article_id, title=title:
                       capture_pdf(blob, article_id, title))
        result["expected_title"] = title
        result["expected_page_count"] = expected_pages
        result["page_count_matches"] = result.get("page_count") == expected_pages
        result["sha256_matches_previous_run"] = (
            result.get("pdf_sha256") == REFERENCE_SHA256[article_id])
        result["verified_for_analysis"] = bool(
            result["pdf_download_verified"] and result.get("text_extraction") == "ok"
            and result.get("title_match") and result["page_count_matches"]
            and result["sha256_matches_previous_run"])
        targets.append(result)
    report = {"gate": "six_official_jryj_pdfs", "targets": targets,
              "target": targets[1],
              "control": None if args.zip_out else probe("independent_publisher_pdf_control", CONTROL, direct=True)}
    report["passed"] = all(x["verified_for_analysis"] for x in targets)
    if report["passed"] and args.zip_out:
        write_delivery_zip(args.zip_out, saved_pdfs)
        report["delivery_zip_name"] = args.zip_out.name
        report["delivery_zip_bytes"] = args.zip_out.stat().st_size
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
