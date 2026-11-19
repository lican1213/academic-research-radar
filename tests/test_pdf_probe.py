import unittest
from pdf_probe import MAX_PDF, pdf_link, probe, valid_pdf

PAGE = "https://www.jryj.org.cn/CN/abstract/abstract1663.shtml"
PDF = "https://www.jryj.org.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=1663"
BLOB = b"%PDF-1.6\\n" + b"1" * 1800 + b"\\n%%EOF"


class PdfProbeTests(unittest.TestCase):
    def test_link_from_actual_publisher_style_html(self):
        page = (b'<a href="/CN/article/downloadArticleFile.do?attachType=PDF&amp;id=1663">'
                b'<img alt="PDF"/> PDF (622 KB)</a>')
        self.assertEqual(pdf_link(PAGE, page), PDF)

    def test_malicious_or_unrelated_link_never_selected(self):
        html = (b'<a href="http://www.jryj.org.cn/p.pdf">PDF</a>'
                b'<a href="https://evil.example/p.pdf">PDF</a>'
                b'<a href="javascript:void(0)">PDF</a>')
        self.assertIsNone(pdf_link(PAGE, html))

    def test_no_guessed_download_url(self):
        self.assertIsNone(pdf_link(PAGE, b"<html><div>PDF (622KB)</div></html>"))

    def test_fake_pdf_and_html_rejected(self):
        self.assertFalse(valid_pdf(b"<html>" + b" " * 2000))
        self.assertFalse(valid_pdf(b"%PDF-1.4" + b" " * 2000))
        self.assertTrue(valid_pdf(BLOB))

    def test_success_needs_real_magic_and_eof(self):
        responses = {
            PAGE: '\u003ca href="/CN/article/downloadArticleFile.do?attachType=PDF&amp;id=1663">正文 PDF\u003c/a>'.encode(),
            PDF: BLOB,
        }
        result = probe("target", PAGE, reader=lambda u, size: responses[u],
                       inspector=lambda b: {"pdf_sha256": "fixture", "pdf_bytes": len(b)})
        self.assertTrue(result["pdf_download_verified"])
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(result["pdf_url"], PDF)

    def test_pdf_server_returns_html_is_not_success(self):
        responses = {
            PAGE: '\u003ca href="/CN/article/downloadArticleFile.do?attachType=PDF&amp;id=1663">正文\u003c/a>'.encode(),
            PDF: b"<html>access denied</html>",
        }
        r = probe("target", PAGE, reader=lambda u, size: responses[u])
        self.assertEqual(r["status"], "not_a_valid_pdf")
        self.assertFalse(r["pdf_download_verified"])

    def test_network_failure_is_explicit(self):
        def broken(u, size):
            raise TimeoutError("upstream timed out")
        r = probe("target", PAGE, reader=broken)
        self.assertEqual((r["status"], r["error_kind"]), ("failed", "TimeoutError"))
        self.assertFalse(r["pdf_download_verified"])

    def test_control_not_treated_as_target(self):
        r = probe("control", PDF, direct=True, reader=lambda u, size: BLOB,
                  inspector=lambda b: {"pdf_bytes": len(b)})
        self.assertTrue(r["pdf_download_verified"])
        self.assertEqual(r["source_url"], PDF)

    def test_publisher_http_url_is_tightly_allowlisted(self):
        from pdf_probe import ARTICLES, approved_url
        for article_id, _, _ in ARTICLES:
            self.assertTrue(approved_url(
                f"http://www.jryj.org.cn/CN/abstract/abstract{article_id}.shtml"))
            self.assertTrue(approved_url(
                f"http://www.jryj.org.cn/CN/article/downloadArticleFile.do?attachType=PDF&id={article_id}"))
        for unsafe in (
            "http://evil.example/CN/abstract/abstract1663.shtml",
            "http://www.jryj.org.cn/CN/abstract/abstract1668.shtml",
            "http://www.jryj.org.cn/CN/abstract/abstract1663.shtml/../../admin",
            "http://www.jryj.org.cn/CN/article/downloadArticleFile.do?attachType=HTML&id=1663",
            "http://www.jryj.org.cn/robots.txt",
        ):
            self.assertFalse(approved_url(unsafe))

    def test_real_style_official_http_link_parsed_without_guess(self):
        page = "http://www.jryj.org.cn/CN/abstract/abstract1663.shtml"
        blob = (b'<a href="http://www.jryj.org.cn/CN/article/downloadArticleFile.do?'
                b'attachType=PDF&amp;id=1663">PDF (622KB)</a>')
        result = pdf_link(page, blob)
        self.assertEqual(result,
                         "http://www.jryj.org.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=1663")

    def test_http_link_cannot_be_redirected_to_unrelated_transport(self):
        page = "http://www.jryj.org.cn/CN/abstract/abstract1663.shtml"
        blob = b'<a href="https://www.jryj.org.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=1663">PDF</a>'
        self.assertIsNone(pdf_link(page, blob))

    def test_pdf_url_recovered_from_magtech_script_not_anchor(self):
        page = "http://www.jryj.org.cn/CN/abstract/abstract1663.shtml"
        html = ('<script>window.pdfUrl="http://www.jryj.org.cn/CN/article/'
                'downloadArticleFile.do?attachType=PDF&amp;id=1663"</script>').encode()
        self.assertEqual(pdf_link(page, html),
                         "http://www.jryj.org.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=1663")

    def test_magtech_url_rejects_mismatched_id_even_in_script(self):
        page = "http://www.jryj.org.cn/CN/abstract/abstract1663.shtml"
        html = ('<script>var pdf="http://www.jryj.org.cn/CN/article/'
                'downloadArticleFile.do?attachType=PDF&amp;id=1662";</script>').encode()
        self.assertIsNone(pdf_link(page, html))

    def test_magtech_parser_prefers_exact_article_over_older_script_link(self):
        page = "http://www.jryj.org.cn/CN/abstract/abstract1663.shtml"
        html = (b'<a href="/CN/article/downloadArticleFile.do?attachType=PDF&amp;id=1662">PDF</a>'
                b'<script>var a="http://www.jryj.org.cn/CN/article/'
                b'downloadArticleFile.do?attachType=PDF&id=1663";</script>')
        self.assertIn("id=1663", pdf_link(page, html))


    def test_pdf_fetch_retries_timeout_but_not_non_retryable_errors(self):
        from unittest.mock import patch
        import pdf_probe
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def geturl(self): return "http://www.jryj.org.cn/CN/abstract/abstract1663.shtml"
            def read(self, size): return b"ok"
        with patch.object(pdf_probe, "urlopen", side_effect=[
            TimeoutError("timeout"), Response()]) as opener:
            blob = pdf_probe.fetch(
                "http://www.jryj.org.cn/CN/abstract/abstract1663.shtml", 100)
            self.assertEqual(blob, b"ok")
            self.assertEqual(opener.call_count, 2)
        with patch.object(pdf_probe, "urlopen", side_effect=TimeoutError("timeout")) as opener:
            with self.assertRaises(TimeoutError):
                pdf_probe.fetch("http://www.jryj.org.cn/CN/abstract/abstract1663.shtml", 100)
            self.assertEqual(opener.call_count, 3)

    def test_delivery_zip_contains_exact_six_pdfs(self):
        import hashlib
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from zipfile import ZipFile
        from pdf_probe import ARTICLES, write_delivery_zip
        fixture = {article_id: BLOB + str(article_id).encode()
                   for article_id, _, _ in ARTICLES}
        expected = {key: hashlib.sha256(blob).hexdigest()
                    for key, blob in fixture.items()}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "six.zip"
            write_delivery_zip(path, fixture, expected)
            with ZipFile(path) as archive:
                self.assertEqual(len(archive.namelist()), 6)
                for article_id, title, _ in ARTICLES:
                    self.assertEqual(archive.read(f"{article_id}_{title}.pdf"),
                                     fixture[article_id])

    def test_delivery_zip_fails_closed_on_wrong_hash_or_missing_pdf(self):
        import hashlib
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from pdf_probe import ARTICLES, write_delivery_zip
        fixture = {article_id: BLOB + str(article_id).encode()
                   for article_id, _, _ in ARTICLES}
        expected = {key: hashlib.sha256(blob).hexdigest()
                    for key, blob in fixture.items()}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "six.zip"
            with self.assertRaisesRegex(ValueError, "incomplete_six_paper_set"):
                write_delivery_zip(path, dict(list(fixture.items())[:5]), expected)
            self.assertFalse(path.exists())
            expected[1663] = "0" * 64
            with self.assertRaisesRegex(ValueError, "pdf_identity_mismatch_1663"):
                write_delivery_zip(path, fixture, expected)
            self.assertFalse(path.exists())

    def test_text_extraction_rejects_corrupt_fixture(self):
        from pdf_probe import inspect_pdf
        result = inspect_pdf(BLOB)
        self.assertEqual(result["pdf_bytes"], len(BLOB))
        self.assertIn(result["text_extraction"], ("failed", "unavailable", "low_confidence"))
        self.assertEqual(len(result["pdf_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
