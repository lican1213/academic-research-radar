import unittest
from pdf_candidate import (find_pdf_url, pdf_url, verify_candidate, evaluate,
                           approved_url)

P = "https://qks.sufe.edu.cn/J/CJYJ/Article/Details/A20260909/CN"
F = "https://qks.sufe.edu.cn/J/PDFFullDown/test-token"


class GenericPdfEvidenceTests(unittest.TestCase):
    def test_parser_reads_sufe_pdf_anchor(self):
        page = b'<a href="/J/PDFFullDown/test-token">PDF download</a>'
        self.assertEqual(find_pdf_url(P, page), F)

    def test_parser_reads_magtech_script_url(self):
        u = "https://sjjj.magtech.com.cn/CN/Y2026/V49/I8/3"
        page = (b'<script>var pdf="/CN/article/downloadArticleFile.do?'
                b'attachType=PDF&amp;id=1551";</script>')
        self.assertEqual(find_pdf_url(u, page),
                         "https://sjjj.magtech.com.cn/CN/article/downloadArticleFile.do?attachType=PDF&id=1551")

    def test_no_pdf_without_explicit_link(self):
        self.assertIsNone(find_pdf_url(P, b'<p>Full text PDF available</p>'))

    def test_external_and_plain_http_rejected(self):
        self.assertFalse(approved_url("https://evil.example/a", "evil.example"))
        self.assertFalse(pdf_url("http://qks.sufe.edu.cn/J/PDFFullDown/a", "qks.sufe.edu.cn"))
        self.assertFalse(pdf_url("https://evil.example/file.pdf", "qks.sufe.edu.cn"))
        self.assertFalse(pdf_url("https://qks.sufe.edu.cn.evil.org/a.pdf", "qks.sufe.edu.cn"))
        self.assertFalse(pdf_url("https://x:q@qks.sufe.edu.cn/a.pdf", "qks.sufe.edu.cn"))

    def test_wrong_article_title_fails_closed_even_with_fallback(self):
        spec = {"key":"a","journal":"J","title":"境外供应链布局研究",
                "article_url":P,"verified_pdf_url":F}
        r=verify_candidate(spec,reader=lambda url, size: b'<p>different study</p>')
        self.assertEqual(r["status"],"article_title_mismatch")

    def test_direct_publisher_pdf_when_article_page_unavailable(self):
        spec={"key":"a","journal":"J","title":"跨境供应链韧性研究",
              "article_url":P,"verified_pdf_url":F,"expected_pages":15}
        def reader(url,size):
            if url==P:raise TimeoutError("temporary catalog outage")
            self.assertEqual(url,F)
            return b"%PDF-1.7"+b"z"*1200+b"%%EOF"
        r=verify_candidate(spec,reader=reader,inspector=lambda blob,title:{
          "title_match":True,"text_extraction":"ok","page_count":15,
          "pdf_sha256":"test","pdf_bytes":len(blob)})
        self.assertTrue(r["text_verified"])
        self.assertEqual(r["link_source"],"independently_verified_publisher_pdf")

    def test_pdf_content_mismatch_cannot_pass(self):
        spec={"key":"a","journal":"J","title":"跨境供应链韧性研究",
              "article_url":P,"verified_pdf_url":F}
        def reader(url,size):
            return ("<p>跨境供应链韧性研究</p>".encode("utf-8") if url==P else
                    b"%PDF-1.7"+b"z"*1200+b"%%EOF")
        r=verify_candidate(spec,reader=reader,inspector=lambda b,title:{
          "title_match":False,"text_extraction":"ok","page_count":15})
        self.assertFalse(r["text_verified"])
        self.assertEqual(r["status"],"pdf_content_unverified")

    def test_one_publisher_cannot_pass_multi_publisher_gate(self):
        spec={"key":"a","journal":"J","title":"供应链",
              "article_url":P,"verified_pdf_url":F,"required":True}
        v=spec|{"key":"b"}
        d=evaluate([spec,v],reader=lambda url,size:(
          "<p>供应链</p>".encode("utf-8") if url==P else b"%PDF-1.7"+b"z"*1200+b"%%EOF"),
          inspector=lambda b,t:{"title_match":True,"text_extraction":"ok","page_count":15})
        self.assertFalse(d["passed"])

    def test_optional_failure_does_not_hide_required_failure(self):
        a={"key":"a","journal":"J","title":"供应链","article_url":P,
           "verified_pdf_url":F,"required":True}
        b={"key":"b","journal":"J","title":"供应链",
           "article_url":"https://xbzs.ecnu.edu.cn/CN/10.1",
           "required":True}
        d=evaluate([a,b],reader=lambda url,size:(
          "<p>供应链</p>".encode("utf-8") if url==P else
          b"%PDF-1.7"+b"z"*1200+b"%%EOF" if url==F else b"<p>none</p>"),
          inspector=lambda blob,title:{"title_match":True,"text_extraction":"ok","page_count":15})
        self.assertFalse(d["passed"])
        self.assertEqual(d["results"][1]["status"],"article_title_mismatch")

    def test_duplicate_and_unbounded_manifest_rejected(self):
        a={"key":"dupe","journal":"J","title":"x","article_url":P}
        with self.assertRaisesRegex(ValueError,"duplicate_candidate_keys"):
            evaluate([a,a])
        with self.assertRaisesRegex(ValueError,"candidate_count_out_of_bounds"):
            evaluate([])
        with self.assertRaisesRegex(ValueError,"candidate_count_out_of_bounds"):
            evaluate([a|{"key":str(i)} for i in range(6)])


if __name__=="__main__":
    unittest.main()
