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

    def test_text_extraction_rejects_corrupt_fixture(self):
        from pdf_probe import inspect_pdf
        result = inspect_pdf(BLOB)
        self.assertEqual(result["pdf_bytes"], len(BLOB))
        self.assertIn(result["text_extraction"], ("failed", "unavailable", "low_confidence"))
        self.assertEqual(len(result["pdf_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
