import tempfile
import unittest
from pathlib import Path

from pdf_cbpt import (
    TARGETS, article_allowed, pdf_allowed, find_explicit_pdfs,
    probe_target, run, validate_document, MAX_PDF,
)

PDF_1 = "https://a.cnki.net/gw/api/get/pdf/ads/v1/pdf/2026/11/alpha.pdf"
PDF_2 = "https://a.cnki.net/gw/api/get/pdf/ads/v1/pdf/2026/11/beta.pdf"
BLOB = b"%PDF-1.7\n" + b"p" * 1700 + b"\n%%EOF"


class WESDeliveryTests(unittest.TestCase):
    def test_two_official_ids_are_distinct_and_bound(self):
        self.assertEqual(len(TARGETS), 2)
        self.assertEqual(len({t["doi"] for t in TARGETS}), 2)
        self.assertTrue(all(article_allowed(t["article_url"]) for t in TARGETS))
        self.assertFalse(article_allowed("http://jing.cbpt.cnki.net/portal/journal/portal/client/paper/ea25a14aef4547e4e652de28ccdb4d03"))

    def test_only_explicit_official_pdfs_allowed(self):
        self.assertTrue(pdf_allowed(PDF_1))
        for url in (
            "http://a.cnki.net/gw/api/get/pdf/ads/v1/pdf/2026/11/alpha.pdf",
            "https://a.cnki.net.evil.test/gw/api/get/pdf/ads/v1/pdf/2026/11/alpha.pdf",
            "https://a.cnki.net/admin/export.pdf",
            "https://evil.test/paper.pdf",
            "https://jing.cbpt.cnki.net/portal/journal/portal/client/paper/abc.pdf#x",
        ):
            self.assertFalse(pdf_allowed(url), url)

    def test_markup_pdf_button_is_not_download_link(self):
        page = b"<html><span>PDF</span><span>Download</span></html>"
        self.assertEqual(find_explicit_pdfs(TARGETS[0]["article_url"], page), [])

    def test_extract_real_literal_url_not_imagined_id(self):
        markup = (f'<a href="{PDF_1}">PDF</a><a href="https://evil.test/p.pdf">bad</a>'
                  f'<meta name="citation_pdf_url" content="{PDF_1}">').encode()
        self.assertEqual(find_explicit_pdfs(TARGETS[0]["article_url"], markup), [PDF_1])

    def test_bad_identity_rejected_after_real_pdf_header(self):
        wrong = validate_document(BLOB, TARGETS[0]["title"],
                                  inspector=lambda data, title: {
                                      "title_match": False, "text_extraction": "ok",
                                      "page_count": 16})
        self.assertFalse(wrong["verified"])

    def test_one_missing_paper_never_creates_partial_zip(self):
        articles = [t["article_url"] for t in TARGETS]
        def reader(url, size):
            if url == articles[0]:
                return (TARGETS[0]["title"] + f'<a href="{PDF_1}">PDF</a>').encode()
            if url == articles[1]:
                return (TARGETS[1]["title"] + "<span>PDF</span>").encode()
            self.assertEqual(url, PDF_1)
            return BLOB
        with tempfile.TemporaryDirectory() as tmp:
            out, zip_out = Path(tmp) / "report.json", Path(tmp) / "delivery.zip"
            report = run(out, zip_out, fetcher=reader,
                         browser=lambda u: ([], {"anonymous": True}),
                         inspector=lambda b, title: {
                             "title_match": True, "text_extraction": "ok",
                             "page_count": 16, "pdf_sha256": "fixture"})
            self.assertFalse(report["passed"])
            self.assertEqual(report["verified_count"], 1)
            self.assertTrue(out.exists())
            self.assertFalse(zip_out.exists())

    def test_two_verified_papers_create_only_two_original_pdfs(self):
        urls = [PDF_1, PDF_2]
        def reader(url, size):
            if url in urls:
                return BLOB
            for i, t in enumerate(TARGETS):
                if url == t["article_url"]:
                    return (t["title"] + f'<a href="{urls[i]}">PDF</a>').encode()
            raise ValueError("unexpected")
        with tempfile.TemporaryDirectory() as tmp:
            out, zip_out = Path(tmp) / "report.json", Path(tmp) / "delivery.zip"
            report = run(out, zip_out, fetcher=reader,
                         browser=lambda u: ([], {"anonymous": True}),
                         inspector=lambda data, title: {
                             "title_match": True, "text_extraction": "ok",
                             "page_count": 16, "pdf_bytes": len(data)})
            self.assertTrue(report["passed"])
            import zipfile
            with zipfile.ZipFile(zip_out) as z:
                self.assertEqual(set(z.namelist()),
                                 {t["key"] + ".pdf" for t in TARGETS})
                self.assertEqual([z.read(t["key"] + ".pdf") for t in TARGETS],
                                 [BLOB, BLOB])

    def test_static_page_failure_still_allows_browser_discovery(self):
        # A JS-driven portal may not put a Chinese title into raw HTML.
        spec = TARGETS[0]
        result, data = probe_target(
            spec,
            fetcher=lambda url, size: (b"<html><div id='app'></div></html>"
                                       if url == spec["article_url"] else BLOB),
            browser=lambda u: ([PDF_1], {"title_visible": True}),
            inspector=lambda b, title: {
                "title_match": True, "text_extraction": "ok", "page_count": 16})
        self.assertEqual(result["status"], "verified_full_pdf")
        self.assertEqual(data, BLOB)


    def test_actual_browser_download_event_can_supply_two_verified_pdfs(self):
        def reader(url, size):
            return (next(t["title"] for t in TARGETS if url == t["article_url"]) +
                    "<span>下载本文</span>").encode()
        with tempfile.TemporaryDirectory() as tmp:
            report = run(Path(tmp) / "report.json", Path(tmp) / "papers.zip",
                         fetcher=reader,
                         browser=lambda url: ([], {"ui_steps": [{"label": "下载本文", "clicked": True},
                                                                     {"label": "PDF", "clicked": True}]}, BLOB),
                         inspector=lambda blob, title: {
                             "title_match": True, "text_extraction": "ok", "page_count": 16})
            self.assertTrue(report["passed"])
            self.assertEqual(report["verified_count"], 2)
            self.assertTrue((Path(tmp) / "papers.zip").exists())

    def test_browser_download_wrong_title_fails_closed(self):
        spec = TARGETS[0]
        row, blob = probe_target(
            spec, fetcher=lambda u, s: spec["title"].encode(),
            browser=lambda u: ([], {"ui_steps": []}, BLOB),
            inspector=lambda data, title: {"title_match": False,
                                           "text_extraction": "ok", "page_count": 16})
        self.assertEqual(row["status"], "no_anonymous_pdf_link_found")
        self.assertIsNone(blob)
        self.assertEqual(row["browser_pdf_identity"], "pdf_identity_or_text_unverified")


if __name__ == "__main__":
    unittest.main()
