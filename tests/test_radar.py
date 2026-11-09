import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from radar import (
    arxiv_items, canonical_arxiv_id, consolidate, crossref_item, fingerprint,
    iso_date, markdown_report, normalize_title, prefilter, run, select_new,
)


UTC_NOW = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)


def example_crossref(doi="10.1000/example"):
    return crossref_item({
        "title": ["Patient Capital and International Patent Families"],
        "DOI": doi,
        "author": [{"given": "A", "family": "Researcher"}],
        "container-title": ["Example Review"],
        "created": {"date-parts": [[2026, 11, 5]]},
        "published-online": {"date-parts": [[2026, 11, 4]]},
        "abstract": "<jats:p>Corporate patents and long-term institutional investors.</jats:p>",
    })


def example_arxiv(version="v1", updated="2026-11-05"):
    feed = f'''<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Patient Capital and International Patent Families</title>
      <id>http://arxiv.org/abs/2611.01234{version}</id>
      <published>2026-11-04T00:00:00Z</published>
      <updated>{updated}T00:00:00Z</updated>
      <summary>A model of international patent families.</summary>
      <author><name>A Researcher</name></author></entry></feed>'''
    return arxiv_items(feed.encode("utf-8"))[0]


class ParsingTests(unittest.TestCase):
    def test_crossref_registration_is_not_publication_date(self):
        item = example_crossref()
        self.assertEqual(item["published_at"], "2026-11-04")
        self.assertEqual(item["event_at"], "2026-11-05")
        self.assertEqual(item["event_type"], "crossref_registration")
        self.assertEqual(item["authors"], ["A Researcher"])
        self.assertNotIn("<jats", item["abstract"])

    def test_arxiv_id_drops_version_but_preserves_version_tracking(self):
        self.assertEqual(canonical_arxiv_id("http://arxiv.org/abs/2611.01234v3"), ("2611.01234", "v3"))
        self.assertEqual(example_arxiv("v2")["id"], example_arxiv("v1")["id"])
        self.assertNotEqual(fingerprint(example_arxiv("v1")), fingerprint(example_arxiv("v2")))

    def test_partial_crossref_date(self):
        self.assertEqual(iso_date({"date-parts": [[2026]]}), "2026-01-01")
        self.assertIsNone(iso_date({"date-parts": [[]]}))

    def test_chinese_title_normalization(self):
        self.assertEqual(normalize_title("【耐心资本】与国际专利布局"), normalize_title("耐心资本与国际专利布局"))


class DedupTests(unittest.TestCase):
    def test_generic_fdi_paper_is_not_project_relevant(self):
        item = prefilter({"id": "doi:10.1/test", "title": "Foreign Direct Investment and Growth in Kenya",
                          "abstract": "Economic growth.", "project": "P1"})
        self.assertFalse(item["eligible"])
        new, _ = select_new([item], {}, UTC_NOW)
        self.assertEqual(new, [])

    def test_supply_chain_without_crossborder_dimension_excluded(self):
        item = prefilter({"id": "doi:10.1/test", "title": "Supply Chain Resilience in Local Construction",
                          "abstract": "Resilience in a construction project."})
        self.assertFalse(item["eligible"])

    def test_crossborder_supply_chain_resilience_is_eligible(self):
        item = prefilter({"id": "doi:10.1/test", "title": "Global Supply Chain Resilience under Geopolitical Shocks",
                          "abstract": "Evidence from exporters."})
        self.assertTrue(item["eligible"])
        self.assertEqual(item["project"], "P1")

    def test_p0_priority_and_p1_cap(self):
        generic = {
            "authors": [], "url": "https://doi.org/10.1000/example", "doi": "10.1000/example",
            "source": "crossref", "sources": ["crossref"], "venue": "", "type": "journal-article",
            "published_at": "2026-11-05", "metadata_created_at": "2026-11-05",
            "event_at": "2026-11-05", "event_type": "crossref_registration", "version": "",
            "abstract": ""
        }
        candidates = [prefilter({**generic, "id": f"doi:10.1/{i}", "doi": f"10.1/{i}",
                                 "title": f"Global Supply Chain Resilience and Internationalization {i}"}) for i in range(15)]
        candidates.append(prefilter({**generic, "id": "doi:10.1/p0", "doi": "10.1/p0",
                                     "title": "International Patent Families and Patient Capital"}))
        new, _ = select_new(candidates, {}, UTC_NOW)
        self.assertEqual(new[0]["project"], "P0")
        self.assertEqual(sum(item["project"] == "P1" for item in new), 7)

    def test_overflow_does_not_mark_undelivered_candidate_as_emitted(self):
        prototype = {
            "authors": [], "url": "https://doi.org/10.1/x", "doi": "10.1/x",
            "source": "crossref", "sources": ["crossref"], "venue": "", "type": "journal-article",
            "published_at": "2026-11-05", "metadata_created_at": "2026-11-05",
            "event_at": "2026-11-05", "event_type": "crossref_registration", "version": "",
            "abstract": ""
        }
        items = [prefilter({**prototype, "id": f"doi:10.1/{i}", "doi": f"10.1/{i}",
                            "title": f"Global Supply Chain Resilience and Trade Routes {i}"}) for i in range(8)]
        first, state = select_new(items, {}, UTC_NOW)
        self.assertEqual(len(first), 7)
        withheld = next(item for item in items if item["id"] not in {a["id"] for a in first})
        self.assertFalse(state[withheld["id"]]["emitted"])
        second, _ = select_new([withheld], state, UTC_NOW)
        self.assertEqual(second[0]["change"], "newly_selected")

    def test_legacy_seen_record_without_emitted_flag_is_recovered(self):
        item = prefilter(example_crossref())
        legacy = {item["id"]: {"fingerprint": fingerprint(item),
                               "title_norm": normalize_title(item["title"]),
                               "doi": item["doi"], "version": "", "last_seen": "2026-11-05"}}
        recovered, updated = select_new([item], legacy, UTC_NOW)
        self.assertEqual(recovered[0]["change"], "newly_selected")
        self.assertTrue(updated[item["id"]]["emitted"])

    def test_crossref_and_arxiv_same_title_merge(self):
        merged = consolidate([prefilter(example_arxiv("v2")), prefilter(example_crossref())])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["id"], "doi:10.1000/example")
        self.assertIn("arxiv:2611.01234", merged[0]["alternate_ids"])
        self.assertEqual(merged[0]["version"], "v2")

    def test_second_run_does_not_repeat_unchanged_candidate(self):
        item = prefilter(example_crossref())
        new, state = select_new([item], {}, UTC_NOW)
        self.assertEqual(len(new), 1)
        again, _ = select_new([item], state, UTC_NOW)
        self.assertEqual(again, [])

    def test_abstract_metadata_refresh_does_not_realert(self):
        item = prefilter(example_crossref())
        _, state = select_new([item], {}, UTC_NOW)
        new_item = dict(item, abstract=item["abstract"] + " Additional result.")
        changed, _ = select_new([new_item], state, UTC_NOW)
        self.assertEqual(changed, [])

    def test_arxiv_version_change_renotifies(self):
        first = prefilter(example_arxiv("v1"))
        _, state = select_new([first], {}, UTC_NOW)
        revised = prefilter(example_arxiv("v2"))
        changed, _ = select_new([revised], state, UTC_NOW)
        self.assertEqual(changed[0]["change"], "new_version")

    def test_switch_source_without_new_version_does_not_realert(self):
        preprint = prefilter(example_arxiv("v2"))
        _, state = select_new([preprint], {}, UTC_NOW)
        # Crossref metadata may be missing from one run. A later source-only
        # observation must not downgrade arXiv version or produce a false alert.
        same = prefilter(example_arxiv("v2"))
        same["version"] = ""
        changed, state2 = select_new([same], state, UTC_NOW)
        self.assertEqual(changed, [])
        self.assertEqual(state2[same["id"]]["version"], "v2")

    def test_formal_doi_after_preprint_is_significant_change(self):
        preprint = prefilter(example_arxiv())
        _, state = select_new([preprint], {}, UTC_NOW)
        journal = prefilter(example_crossref())
        changed, _ = select_new([journal], state, UTC_NOW)
        self.assertEqual(changed[0]["change"], "formal_publication_or_doi_added")

    def test_abstract_is_not_redistributed_in_output(self):
        item = prefilter(example_crossref())
        new, _ = select_new([item], {}, UTC_NOW)
        self.assertNotIn("abstract", new[0])

    def test_different_doi_same_title_does_not_spam(self):
        item = prefilter(example_crossref())
        _, state = select_new([item], {}, UTC_NOW)
        duplicate = prefilter(example_crossref("10.1000/different"))
        new, _ = select_new([duplicate], state, UTC_NOW)
        self.assertEqual(new, [])

    def test_old_state_expires(self):
        item = prefilter(example_crossref())
        old = {"title:" + normalize_title(item["title"]): {
            "fingerprint": fingerprint(item), "title_norm": normalize_title(item["title"]),
            "doi": item["doi"], "version": "", "emitted": True, "last_seen": "2025-01-01"
        }}
        new, refreshed = select_new([item], old, UTC_NOW)
        self.assertEqual(new, [])  # Still deduplicate if re-encountered today.
        self.assertEqual(refreshed["title:" + normalize_title(item["title"])]["last_seen"], "2026-11-06")


class PipelineTests(unittest.TestCase):
    def fake_source(self, items, status="ok"):
        return lambda since: (items, {"status": status, "queries_ok": 1 if status == "ok" else 0,
                                      "queries_total": 1, "records": len(items),
                                      "errors": [] if status == "ok" else ["simulated timeout"]})

    def test_first_scan_and_followup(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            first = run(folder, UTC_NOW, crossref=self.fake_source([example_crossref()]), arxiv=self.fake_source([]))
            self.assertEqual(first["status"], "ok")
            self.assertEqual(len(first["new_candidates"]), 1)
            self.assertEqual(first["prefilter_pass_count"], 1)
            self.assertNotIn("abstract", first["prefilter_diagnostics"][0])
            second = run(folder, UTC_NOW, crossref=self.fake_source([example_crossref()]), arxiv=self.fake_source([]))
            self.assertEqual(second["new_candidates"], [])
            self.assertEqual(json.loads((folder / "latest.json").read_text())["status"], "ok")

    def test_partial_failure_not_misreported_as_no_data(self):
        with tempfile.TemporaryDirectory() as temp:
            report = run(Path(temp), UTC_NOW,
                         crossref=self.fake_source([example_crossref()]), arxiv=self.fake_source([], "failed"))
            self.assertEqual(report["status"], "degraded")
            self.assertEqual(report["source_status"]["arxiv"]["status"], "failed")

    def test_complete_outage_preserves_seen_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "seen.json").write_text('{"known":{"last_seen":"2026-11-05","fingerprint":"abc"}}')
            report = run(folder, UTC_NOW, crossref=self.fake_source([], "failed"), arxiv=self.fake_source([], "failed"))
            self.assertEqual(report["status"], "failed")
            self.assertIn("known", json.loads((folder / "seen.json").read_text()))
            self.assertIn("failed", markdown_report(report))



# Chinese journal monitor adversarial tests: independent source health and time semantics.
import chinese_journals as cj
from unittest.mock import patch


class ChineseJournalTests(unittest.TestCase):
    SITE = "https://sjjj.magtech.com.cn/CN/home"
    def toc(self, issue=10, articles=None):
        if articles is None:
            articles = [("人工智能专利首发竞赛中的逆境突破：失败何以激励创新", "100"),
                        ("出口管制、技术脱钩与人才培养：来自中国高考的证据", "101")]
        anchors = "".join(
            f'<a href="/CN/Y2026/V49/I{issue}/{slug}">{title}</a>' for title, slug in articles)
        return (f'<html><h1>世界经济</h1><p>2026年, 49卷, 第{issue}期</p>'
                f'<p>刊出日期：2026-10-10</p>{anchors}</html>').encode()

    def test_official_toc_extracts_articles_and_issue_date(self):
        issue, date, articles = cj.parse_toc(self.toc(), journal="世界经济",
                                            kind="publisher", url=self.SITE)
        self.assertEqual(issue, "2026-10")
        self.assertEqual(date, "2026-10-10")
        self.assertEqual(len(articles), 2)

    def test_catalog_only_is_not_ok(self):
        page = "<html><h1>经济研究</h1><p>2026年 第10期</p><span>耐心资本与企业海外布局</span></html>"
        issue, date, articles = cj.parse_toc(page.encode(), journal="经济研究", kind="catalog",
                                            url="https://ncpssd.org/journal/details?gch=95645X")
        self.assertEqual(issue, "2026-10")
        self.assertIsNone(date)
        self.assertEqual(articles, [])

    def test_initial_scan_baselines_then_new_issue_surfaces_once(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            url = self.SITE
            with patch.object(cj, "JOURNALS", (("world_economy", "世界经济", "publisher", url),)):
                initial = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _url: self.toc())
                self.assertEqual(initial["new_candidates"], [])
                self.assertEqual(initial["source_status"]["status"], "ok")
                repeat = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _url: self.toc())
                self.assertEqual(repeat["new_candidates"], [])
                later = self.toc(issue=11, articles=[
                    ("突破式创新与耐心资本长期投入的交互机制", "202")])
                changed = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _url: later)
                self.assertEqual(len(changed["new_candidates"]), 1)
                candidate = changed["new_candidates"][0]
                self.assertIsNone(candidate["published_at"])
                self.assertFalse(candidate["date_verified"])
                self.assertEqual(candidate["event_type"], "first_seen_in_toc")
                self.assertEqual(candidate["issue"], "2026-11")
                self.assertEqual(cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _url: later)["new_candidates"], [])

    def test_regressed_index_does_not_reemit_or_overwrite_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            url = self.SITE
            with patch.object(cj, "JOURNALS", (("world_economy", "世界经济", "publisher", url),)):
                cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _url: self.toc(issue=11))
                stale = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _url: self.toc(issue=9))
                self.assertEqual(stale["source_status"]["journals"]["world_economy"]["status"], "stale_index")
                self.assertEqual(stale["new_candidates"], [])
                self.assertEqual(json.loads((folder / "chinese_seen.json").read_text())["world_economy"]["issue"], "2026-11")

    def test_failed_source_preserves_ledger_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            url = self.SITE
            with patch.object(cj, "JOURNALS", (("world_economy", "世界经济", "publisher", url),)):
                cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _url: self.toc())
                def fail(_url):
                    raise OSError("site timeout")
                report = cj.scan_chinese_journals(folder, UTC_NOW, get=fail)
                self.assertEqual(report["source_status"]["status"], "failed")
                self.assertEqual(report["source_status"]["journals"]["world_economy"]["status"], "failed")
                self.assertEqual(json.loads((folder / "chinese_seen.json").read_text())["world_economy"]["issue"], "2026-10")

    def test_no_article_without_concrete_link_or_fake_date(self):
        html = '<h1>世界经济</h1><p>2026年,49卷,第11期</p>' \
               '<a href="/CN/current">耐心资本与国际专利布局深度</a>' \
               '<a href="https://evil.example/CN/Y2026/V49/I11/10">专利文本与创新质量</a>'
        issue, date, articles = cj.parse_toc(html.encode(), journal="世界经济",
                                            kind="publisher", url=self.SITE)
        self.assertEqual(issue, "2026-11")
        self.assertIsNone(date)
        self.assertEqual(articles, [])

    def test_sufe_real_detail_links_exclude_issuetoc_and_verify_online_date(self):
        url = "https://qks.sufe.edu.cn/J/CJYJ/Article/CurrentIssue/CN"
        source = (
            '<h1>财经研究</h1><div>2026年52卷第9期</div>'
            '<a href="/J/CJYJ/Article/2026/09/CN">《财经研究》第52卷第09期</a>'
            '<a href="/J/CJYJ/Article/Details/A0pgbFuTsz-vRzo-GypL-0h9O-AptmzpGperJG/CN">'
            '政府赋能企业“出海”：国家海外知识产权纠纷应对指导中心与企业对外直接投资</a>'
            '<a href="/J/CJYJ/Article/Details/A0pgbFuTsz-vRzo-GypL-0h9O-AptmzpGperJG/CN">'
            '母国支持如何驱动企业对外直接投资</a>'
            '<p>在线出版日期：2026年11月3日</p>'
            '<p>doi:10.16538/j.cnki.jfe.20260611.202</p>'
        ).encode()
        issue, date, articles = cj.parse_toc(source, journal="财经研究",
                                            kind="publisher", url=url)
        self.assertEqual(issue, "2026-09")
        self.assertIsNone(date)
        self.assertEqual(len(articles), 1)
        self.assertTrue(articles[0]["title"].startswith("政府赋能企业"))
        self.assertEqual(articles[0]["published_at"], "2026-11-03")
        self.assertEqual(articles[0]["doi"], "10.16538/j.cnki.jfe.20260611.202")

    def test_sufe_superscript_title_precedes_abstract_link_same_url(self):
        url = "https://qks.sufe.edu.cn/J/CJYJ/Article/2026/09/CN"
        detail = "/J/CJYJ/Article/Details/A0pgbFuTsz-vRzo-GypL-0h9O-AptmzpGperJG/CN"
        source = (
            '<h1>财经研究</h1><p>2026年第09期</p>'
            f'<a href="{detail}">注册制改革与企业环境信息披露<sup>*</sup>'
            '——基于同行溢出效应的视角</a>'
            f'<a href="{detail}">文章研究了信息披露监管带来的经济后果与机制......</a>'
            '<p>在线出版日期：2026年11月3日</p>'
            '<p>doi:10.16538/j.cnki.jfe.20260619.301</p>'
        ).encode()
        issue, _, papers = cj.parse_toc(source, journal="财经研究", kind="publisher", url=url)
        self.assertEqual(issue, "2026-09")
        self.assertEqual(len(papers), 1)
        self.assertTrue(papers[0]["title"].startswith("注册制改革"))
        self.assertEqual(papers[0]["published_at"], "2026-11-03")

    def test_first_scan_recent_publisher_date_surfaces_without_calling_it_today(self):
        with tempfile.TemporaryDirectory() as temp:
            url = "https://qks.sufe.edu.cn/J/CJYJ/Article/CurrentIssue/CN"
            detail = "/J/CJYJ/Article/Details/A0pgbFuTsz-vRzo-GypL-0h9O-AptmzpGperJG/CN"
            page = ('<h1>财经研究</h1><p>2026年第09期</p>'
                    f'<a href="{detail}">政府赋能企业出海与知识产权保护研究</a>'
                    '<p>在线出版日期：2026年11月3日</p>').encode()
            with patch.object(cj, "JOURNALS", (("finance_economics", "财经研究", "publisher", url),)):
                result = cj.scan_chinese_journals(Path(temp), UTC_NOW, get=lambda _: page)
                self.assertEqual(len(result["new_candidates"]), 1)
                self.assertEqual(result["new_candidates"][0]["published_at"], "2026-11-03")
                self.assertTrue(result["new_candidates"][0]["date_verified"])
                self.assertEqual(cj.scan_chinese_journals(Path(temp), UTC_NOW, get=lambda _: page)["new_candidates"], [])

    def test_primary_tls_failure_uses_explicit_catalog_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            primary = "https://www.jryj.org.cn/CN/1002-7246/current.shtml"
            fallback = "https://m.ncpssd.cn/journal/details?gch=97926X&langType=1&nav=1"
            def source(url):
                if url == primary:
                    raise OSError("TLS hostname mismatch")
                return "<h1>金融研究</h1><p>2026年 第7期</p>".encode()
            with patch.object(cj, "JOURNALS", (("financial_research", "金融研究", "publisher", primary),)):
                result = cj.scan_chinese_journals(Path(temp), UTC_NOW, get=source)
                j = result["source_status"]["journals"]["financial_research"]
                self.assertEqual(j["status"], "catalog_only")
                self.assertEqual(j["source_kind"], "catalog")
                self.assertEqual(j["url"], fallback)
                self.assertIn("primary_failure", j)
                self.assertEqual(result["source_status"]["status"], "degraded")

    def test_english_pipeline_report_has_independent_chinese_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            fake_c = lambda out, now: {"source_status": {
                "status": "degraded", "queries_ok": 1, "queries_total": 7,
                "records": 6, "errors": ["经济研究: catalog_only"],
                "journals": {"economic_research": {
                    "journal": "经济研究", "url": "https://ncpssd.org/example",
                    "source_kind": "catalog", "status": "catalog_only",
                    "issue": "2026-10", "article_count": 0, "reason": "issue_visible"}}},
                "new_candidates": []}
            report = run(folder, UTC_NOW,
                         crossref=lambda since: ([], {"status":"ok","queries_ok":1,"queries_total":1,"records":0,"errors":[]}),
                         arxiv=lambda since: ([], {"status":"ok","queries_ok":1,"queries_total":1,"records":0,"errors":[]}),
                         chinese=fake_c)
            self.assertEqual(report["status"], "degraded")
            self.assertIn("chinese_journals", report["source_status"])
            self.assertIn("经济研究", (folder / "latest.md").read_text())


if __name__ == "__main__":
    unittest.main()
