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
    def test_p1a_recall_following_and_plural(self):
        titles = [
            "Customer-following FDI and relationship survival",
            "Foreign subsidiaries and supplier relationship stability",
            "Geographical proximity and buyer-supplier relationship duration",
            "Institutional and relational underpinnings of vertical FDI spillovers in international buyer-supplier relationships",
            "上下游企业抱团出海与供应链关系稳定",
        ]
        for i, title in enumerate(titles):
            with self.subTest(title=title):
                item = prefilter({**example_crossref(f"10.1000/p1a{i}"), "title": title, "abstract": ""})
                self.assertEqual(item["project"], "P1A")
                self.assertTrue(item["eligible"])
                self.assertGreaterEqual(item["prefilter_score"], 40)

    def test_p1a_reject_generic_domestic_logistics(self):
        item = prefilter({"title": "Geographic proximity in local supply chain warehouse logistics", "abstract": ""})
        self.assertFalse(item["eligible"])

    def test_p1a_p0_precedence_and_cross_day_cap(self):
        patent = prefilter({**example_crossref(), "title": "International patent families of foreign subsidiaries in buyer-supplier relationships"})
        self.assertEqual(patent["project"], "P0")
        items = [prefilter({**example_crossref(f"10.1000/a{i}"), "title": f"Buyer-supplier relationship survival and foreign subsidiaries {i}", "abstract": ""}) for i in range(7)]
        first, state = select_new(items + [patent], {}, UTC_NOW)
        self.assertEqual(first[0]["project"], "P0")
        self.assertEqual(sum(x["project"] == "P1A" for x in first), 6)
        from datetime import timedelta
        second, state = select_new(items + [patent], state, UTC_NOW + timedelta(days=1))
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["change"], "newly_selected")
        third, _ = select_new(items + [patent], state, UTC_NOW + timedelta(days=2))
        self.assertEqual(third, [])

    def test_p1a_name_and_score_are_not_quality_claims(self):
        self.assertIn("prefilter", markdown_report({"generated_at": UTC_NOW.isoformat(), "status": "ok", "new_candidates": [dict(prefilter({**example_crossref(), "title": "Buyer-supplier relationship survival and foreign subsidiaries"}), change="new")], "source_status": {}}))

    def test_collaborative_internationalization_track(self):
        for title in ('Buyer-supplier relationship termination and foreign subsidiary colocation', '产业链协同出海与供应链关系稳定'):
            item = prefilter({**example_crossref(), 'title': title, 'abstract': ''})
            self.assertEqual(item['project'], 'P1A')
            self.assertTrue(item['eligible'])
            new, state = select_new([item], {}, UTC_NOW)
            self.assertEqual(len(new), 1)
            self.assertEqual(select_new([item], state, UTC_NOW)[0], [])

    def test_local_proximity_without_supply_relationship_excluded(self):
        item = prefilter({'title': 'Geographic proximity and urban housing', 'abstract': ''})
        self.assertFalse(item['eligible'])

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

    def test_sufe_detail_links_and_toc_date_not_publication_date(self):
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
        self.assertEqual(articles[0]["toc_online_at"], "2026-11-03")
        self.assertNotIn("published_at", articles[0])
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
        self.assertEqual(papers[0]["toc_online_at"], "2026-11-03")
        self.assertNotIn("published_at", papers[0])

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
                self.assertIsNone(result["new_candidates"][0]["published_at"])
                self.assertEqual(result["new_candidates"][0]["toc_online_at"], "2026-11-03")
                self.assertFalse(result["new_candidates"][0]["date_verified"])
                self.assertEqual(cj.scan_chinese_journals(Path(temp), UTC_NOW, get=lambda _: page)["new_candidates"], [])

    def test_quant_publisher_2026_issue_and_real_article_link(self):
        url = "https://www.jqte.net/sljjjsjjyj/ch/index.aspx"
        html = ('<h1>数量经济技术经济研究</h1><div>本刊最新目录</div>'
                '<a href="/sljjjsjjyj/ch/reader/view_abstract.aspx?file_no=20261007&flag=1">'
                '外部供应风险、技术结构与自主创新能力提升</a>'
                '<span>2026,(10):166-191</span>'
                '<a href="/sljjjsjjyj/ch/reader/download.aspx?file_no=20261007">下载全文及数据</a>').encode()
        issue, date, articles = cj.parse_toc(html, journal="数量经济技术经济研究",
                                            kind="publisher", url=url)
        self.assertEqual(issue, "2026-10")
        self.assertIsNone(date)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "外部供应风险、技术结构与自主创新能力提升")
        self.assertIsNone(articles[0]["toc_online_at"])

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


class ChineseRSSCoverageTests(unittest.TestCase):
    def rss(self, title="邻近布局与跨境供应链关系稳定", journal="经济研究", date="Thu, 05 Nov 2026 12:00:00 GMT"):
        return (f"<rss version='2.0'><channel><title>{journal}</title>"
                f"<item><title>{title}</title>"
                "<link>https://kns.cnki.net/kcms/detail/detail.aspx?filename=JJYJ202611001</link>"
                f"<pubDate>{date}</pubDate><author>示例作者</author></item>"
                "</channel></rss>").encode()

    def test_rss_identity_and_date_are_independent(self):
        rows = cj.parse_rss(self.rss(), "经济研究")
        self.assertEqual(rows[0]["rss_event_at"], "2026-11-05")
        self.assertNotIn("published_at", rows[0])
        with self.assertRaises(ValueError):
            cj.parse_rss(self.rss(journal="金融研究"), "经济研究")

    def test_rss_html_empty_and_foreign_links_do_not_pass(self):
        for payload in (b"", b"<html>captcha</html>", self.rss().replace(b"kns.cnki.net", b"evil.example")):
            with self.subTest(payload=payload):
                with self.assertRaises((ValueError, cj.ET.ParseError)):
                    cj.parse_rss(payload, "经济研究")

    def test_toc_failure_rss_recovers_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            journal = ("economic_research", "经济研究", "catalog", "https://ncpssd.org/example")
            with patch.object(cj, "JOURNALS", (journal,)):
                first = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _: "<h1>经济研究</h1><p>2026年 第9期</p>".encode(), rss_get=lambda _: self.rss())
                self.assertEqual(first["source_status"]["journals"]["economic_research"]["status"], "rss_only")
                self.assertEqual(first["source_status"]["queries_ok"], 1)
                self.assertEqual(len(first["new_candidates"]), 1)
                self.assertIsNone(first["new_candidates"][0]["published_at"])
                self.assertFalse(first["new_candidates"][0]["date_verified"])
                second = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _: "<h1>经济研究</h1><p>2026年 第9期</p>".encode(), rss_get=lambda _: self.rss())
                self.assertEqual(second["new_candidates"], [])
                self.assertTrue(json.loads((folder/"chinese_seen.json").read_text())["economic_research"]["rss_baselined"])

    def test_sufe_new_detail_path_and_issue_format(self):
        page = ("<h1>财经研究</h1><p>2026年第09期 共11篇</p>"
                "<a href='/J/CJYJ/Article/Details/pgbFuTsz-vRzo-GypL-0h9O-AptmzpGperJG'>政府赋能企业出海与知识产权保护研究</a>"
                "<a href='/J/CJYJ/Article/2026/09/CN'>财经研究第九期目录</a>").encode()
        issue, _, rows = cj.parse_toc(page, journal="财经研究", kind="publisher", url="https://qks.sufe.edu.cn/J/CJYJ.html/CN")
        self.assertEqual(issue, "2026-09")
        self.assertEqual(len(rows), 1)

    def test_catalog_recovery_baselines_old_same_issue(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            url = "https://sjjj.magtech.com.cn/CN/home"
            with patch.object(cj, "JOURNALS", (("world_economy", "世界经济", "publisher", url),)):
                cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _: "<h1>世界经济</h1><p>2026年 第9期</p>".encode())
                result = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _: "<h1>世界经济</h1><p>2026年 第9期</p><a href='/CN/Y2026/V49/I9/12'>跨境供应链关系与企业出海</a>".encode())
                self.assertEqual(result["new_candidates"], [])
                self.assertEqual(result["source_status"]["queries_ok"], 1)

    def test_nine_monitored_journals_have_rss_codes(self):
        self.assertEqual(len(cj.JOURNALS), 9)
        self.assertEqual(set(cj.RSS_CODES), {x[0] for x in cj.JOURNALS})


class ChineseRecoveryTests(unittest.TestCase):
    def test_mixed_sufe_rows_bind_individual_issue(self):
        url = "https://qks.sufe.edu.cn/J/CJYJ/Article/Latest"
        page = ("<h1>财经研究</h1><p>2026年第09期</p>"
                "<a href='/J/CJYJ/Article/Details/A0D4FFPwQu-dBL4-uLdN-7nqu-nnsVUTr60cyJ/CN'>耐心资本支持与企业绿色创新质量</a>"
                "<p>2026年第07期</p>"
                "<a href='/J/CJYJ/Article/Details/A0pgbFuTsz-vRzo-GypL-0h9O-AptmzpGperJG/CN'>政府赋能企业出海与知识产权保护研究</a>"
                "<p>2026年第09期</p>"
                "<a href='/J/CJYJ/Article/Details/A0vM3daegN-oHdT-Onlc-LKQU-f0bPO5rwTyPZ/CN'>无明确期次的中文研究文章</a>").encode()
        issue, _, rows = cj.parse_toc(page, journal="财经研究", kind="publisher", url=url)
        self.assertEqual(issue, "2026-09")
        self.assertEqual([x["issue"] for x in rows], ["2026-07", "2026-09", None])

    def test_trade_portal_recovers_exact_counterexample(self):
        url = "https://gjmw.cbpt.cnki.net/portal/journal/portal/client/index"
        page = ("<h1>国际贸易问题</h1><h2>2026年10期</h2>"
                "<a href='/portal/journal/portal/client/paper/7f6078a0cec828f7581a0bc4ff569adf'>专利出海、创新激励与内外贸一体化</a>"
                "<p>2026 年 10 期 No.526 DOI:10.13510/j.cnki.jit.2026.10.007</p>"
                "<a href='/portal/journal/portal/client/paper/'>期刊目录不是文章记录</a>"
                "<p>2026年11期</p>").encode()
        issue, _, rows = cj.parse_toc(page, journal="国际贸易问题", kind="publisher", url=url)
        self.assertEqual(issue, "2026-10")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["issue"], "2026-10")
        self.assertEqual(rows[0]["doi"], "10.13510/j.cnki.jit.2026.10.007")

    def test_structured_index_validates_exact_journal_and_link(self):
        row = {"title": "<em>专利出海</em>、创新激励与内外贸一体化", "cbw_name":"国际贸易问题",
               "doi":"10.13510/j.cnki.jit.2026.10.007", "years":"2026", "num":"10", "date":"2026-10-25"}
        payload = json.dumps({"result": True, "data":{"rows":[row, dict(row, cbw_name="国际贸易"), dict(row, doi="", HtmlUrl="https://evil.example/article/fake")]}}).encode()
        items = cj.parse_ncpssd(payload, {"国际贸易问题"})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["issue"], "2026-10")
        self.assertNotIn("published_at", items[0])
        with self.assertRaises(ValueError):
            cj.parse_ncpssd(b'{"result":false}', {"国际贸易问题"})

    def test_index_recovery_is_backfill_not_full_coverage_and_dedup(self):
        row = {"title":"专利出海、创新激励与内外贸一体化","cbw_name":"国际贸易问题","doi":"10.13510/j.cnki.jit.2026.10.007","years":"2026","num":"10","date":"2026-10-25"}
        payload = json.dumps({"result":True,"data":{"rows":[row]}}).encode()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            with patch.object(cj, "JOURNALS", (("international_trade","国际贸易问题","catalog","https://ncpssd.org/example"),)):
                first = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _: "<h1>国际贸易问题</h1><p>2026年第9期</p>".encode(), ncpssd_get=lambda _:payload)
                self.assertEqual(first["source_status"]["queries_ok"], 0)
                self.assertEqual(len(first["new_candidates"]),1)
                self.assertEqual(first["new_candidates"][0]["event_type"],"index_backfill")
                self.assertIsNone(first["new_candidates"][0]["published_at"])
                again = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _: "<h1>国际贸易问题</h1><p>2026年第9期</p>".encode(), ncpssd_get=lambda _:payload)
                self.assertEqual(again["new_candidates"],[])



class IssueFirstTests(unittest.TestCase):
    def test_public_catalog_title_author_pages_no_guessed_url(self):
        url = "https://ncpssd.org/journal/details.aspx?gch=95645X"
        page = ("<h1>经济研究</h1><h2>2026年 第9期</h2>"
                "<div><span>数据要素冲击、信息摩擦与供应链关系建立</span>"
                "<span>施炳展[1,2];李启正[3];熊治[4]</span><span>(143-164)</span></div>"
                "<div><span>机器人应用与制造业企业生产链延伸——基于稳链强链视角的考察</span>"
                "<span>吴腊梅[1,2];彭水军[3];张亮[4,5];周上尧[4,5]</span><span>(25-48)</span></div>"
                "<h2>2026年 第9期 整刊阅读</h2>"
                "<div>不应混入当期目录的推荐文章</div><div>示例[1]</div><div>(10-20)</div>").encode()
        issue, _, rows = cj.parse_toc(page, journal="经济研究", kind="catalog", url=url)
        self.assertEqual(issue, "2026-09")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "数据要素冲击、信息摩擦与供应链关系建立")
        self.assertEqual(rows[0]["pages"], "143-164")
        self.assertEqual(rows[0]["url_scope"], "issue_catalog")
        self.assertEqual(rows[0]["url"], url)
        self.assertIsNone(rows[0]["doi"])

    def test_current_issue_excludes_previous_issue_and_hot_links(self):
        url = "https://gjmw.cbpt.cnki.net/portal/journal/portal/client/paper_list/type_benqi"
        page = ("<h1>国际贸易问题</h1><h2>2026年 10期</h2>"
                "<a href='/portal/journal/portal/client/paper/7f6078a0cec828f7581a0bc4ff569adf'>专利出海、创新激励与内外贸一体化</a>"
                "<p>刘博聪;李磊;李川川;</p><p>2026 年 10 期 No.526 ;</p>"
                "<a href='/portal/journal/portal/client/paper/12345678901234567890123456789012'>历史热门论文不能混入最新期</a>"
                "<p>2025年 8期 No.512</p>"
                "<a href='/portal/journal/portal/client/paper/abcdefabcdefabcdefabcdefabcdefab'>无期次证据的推荐文章不能纳入</a>").encode()
        issue, _, rows = cj.parse_toc(page, journal="国际贸易问题", kind="publisher", url=url)
        self.assertEqual(issue, "2026-10")
        self.assertEqual([x["title"] for x in rows], ["专利出海、创新激励与内外贸一体化"])
        self.assertEqual(rows[0]["issue"], "2026-10")

    def test_chinese_index_keys_not_empty_or_collapsed(self):
        self.assertEqual(cj.title_key("专利出海、创新激励与内外贸一体化"), "专利出海创新激励与内外贸一体化")
        self.assertNotEqual(cj.title_key("专利出海"), cj.title_key("耐心资本"))

    def test_catalog_metadata_status_does_not_claim_paper_links(self):
        url = "https://ncpssd.org/journal/details.aspx?gch=95645X"
        page = ("<h1>经济研究</h1><h2>2026年 第9期</h2>"
                "<p>数据要素冲击、信息摩擦与供应链关系建立</p>"
                "<p>施炳展[1,2];李启正[3];熊治[4]</p><p>(143-164)</p>").encode()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/"chinese_seen.json").write_text(json.dumps({"economic_research":{"issue":"2026-09","articles":[""],"baselined":True}}))
            with patch.object(cj, "JOURNALS", (("economic_research","经济研究","catalog",url),)):
                first = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _:page)
                j = first["source_status"]["journals"]["economic_research"]
                self.assertEqual(j["status"], "toc_metadata")
                self.assertEqual(j["article_link_count"], 0)
                self.assertEqual(j["issue_metadata_count"], 1)
                self.assertEqual(first["source_status"]["status"], "degraded")
                self.assertEqual(first["new_candidates"][0]["event_type"], "issue_backfill")
                self.assertIsNone(first["new_candidates"][0]["published_at"])
                self.assertEqual(cj.scan_chinese_journals(folder, UTC_NOW,get=lambda _:page)["new_candidates"],[])
                self.assertNotIn("",json.loads((folder/"chinese_seen.json").read_text())["economic_research"]["articles"])



class ProductionGateTests(unittest.TestCase):
    def test_quant_live_history_never_enters_increment(self):
        url = "https://www.jqte.net/sljjjsjjyj/ch/index.aspx"
        page = ("<h1>数量经济技术经济研究</h1><p>2026,(10):1-20</p>"
                "<a href='/sljjjsjjyj/ch/reader/view_abstract.aspx?file_no=20261007&flag=1'>外部供应风险、技术结构与自主创新能力提升</a>"
                "<p>2026,(10):166-191</p>"
                "<a href='/sljjjsjjyj/ch/reader/view_abstract.aspx?file_no=20220909&flag=1'>交错双重差分：处理效应异质性与估计方法选择</a>"
                "<p>2026,(10):20-30</p>"
                "<a href='/sljjjsjjyj/ch/reader/view_abstract.aspx?file_no=20130301&flag=1'>企业出口对其工资影响的再分析</a>").encode()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/"chinese_seen.json").write_text(json.dumps({"quant_economics":{"issue":"2026-09","articles":["旧标题"],"baselined":True}}))
            with patch.object(cj, "JOURNALS", (("quant_economics","数量经济技术经济研究","publisher",url),)):
                result = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _:page)
                self.assertEqual([x["title"] for x in result["new_candidates"]], ["外部供应风险、技术结构与自主创新能力提升"])
                snap = result["source_status"]["journals"]["quant_economics"]["article_snapshot"]
                self.assertEqual(len(snap), 1)
                self.assertFalse(snap[0]["link_verified"])
                self.assertEqual(cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _:page)["new_candidates"], [])

    def test_mixed_rows_not_consumed_and_recover_when_bound(self):
        url = "https://qks.sufe.edu.cn/J/CJYJ/Article/Latest"
        a = "/J/CJYJ/Article/Details/abcdefghijklm/CN"
        b = "/J/CJYJ/Article/Details/abcdefghijkln/CN"
        title = "供应链信息隐藏如何影响企业创新"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/"chinese_seen.json").write_text(json.dumps({"finance_economics":{"issue":"2026-09","articles":["旧标题"],"baselined":True}}))
            mixed = (f"<h1>财经研究</h1><p>2026年第9期</p><a href='{a}'>政府赋能企业出海与知识产权保护研究</a><p>2026年第9期</p><a href='{b}'>{title}</a>").encode()
            with patch.object(cj, "JOURNALS", (("finance_economics","财经研究","publisher",url),)):
                result = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _:mixed)
                j = result["source_status"]["journals"]["finance_economics"]
                self.assertEqual(j["status"], "mixed_links")
                self.assertEqual(len(j["article_snapshot"]), 2)
                self.assertNotIn(cj.title_key(title),json.loads((folder/"chinese_seen.json").read_text())["finance_economics"]["articles"])
                recovery = mixed + "<p>2026年第9期</p>".encode()
                result = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _:recovery)
                self.assertEqual([x["title"] for x in result["new_candidates"]], [title])

    def test_catalog_only_does_not_refresh_article_success(self):
        url = "https://ncpssd.org/example"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/"chinese_seen.json").write_text(json.dumps({"financial_research":{"issue":"2026-07","articles":[],"last_success_at":"2026-11-01","baselined":True}}))
            with patch.object(cj, "JOURNALS", (("financial_research","金融研究","catalog",url),)):
                cj.scan_chinese_journals(folder, UTC_NOW, get=lambda _:"<h1>金融研究</h1><p>2026年第7期</p>".encode())
            state = json.loads((folder/"chinese_seen.json").read_text())["financial_research"]
            self.assertEqual(state["last_success_at"],"2026-11-01")
            self.assertIn("last_issue_observed_at", state)

    def test_stable_detail_url_bridges_title_variants(self):
        a = {"title":"同乡网络如何促进资本跨地区流动","url":"https://qks.sufe.edu.cn/J/CJYJ/Article/Details/abcdefghijklm/CN","url_scope":"article_detail"}
        b = dict(a,title="同乡网络如何促进资本跨地区流动——基于异地新设企业的经验证据",url=a["url"].removesuffix("/CN"))
        self.assertTrue(cj.article_keys(a) & cj.article_keys(b))
        catalog = dict(a,url_scope="issue_catalog")
        self.assertFalse(any(x.startswith("url:") for x in cj.article_keys(catalog)))

if __name__ == "__main__":
    unittest.main()


class SourceTransportBudgetTests(unittest.TestCase):
    def test_dns_failure_short_circuits_one_host_only(self):
        import socket
        import urllib.error
        from chinese_journals import ScanHostBudget
        gate = ScanHostBudget()
        called = []
        def broken(_):
            called.append(1)
            raise urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))
        url = "https://navi.cnki.net/knavi/rss/JJYJ"
        with self.assertRaises(urllib.error.URLError):
            gate.fetch(url, broken, "JJYJ")
        with self.assertRaisesRegex(OSError, "host_circuit_open.*dns_resolution_failed"):
            gate.fetch(url, broken, "GGYY")
        self.assertEqual(len(called), 1)
        self.assertEqual(gate.fetch("https://different.example.org/", lambda x: x, 17), 17)

    def test_timeouts_short_circuit_after_two_independent_attempts(self):
        from chinese_journals import ScanHostBudget
        gate = ScanHostBudget()
        called = []
        def timeout(_):
            called.append(1)
            raise TimeoutError("The read operation timed out")
        url = "https://www.ncpssd.cn/searchHandler/search"
        for _ in range(2):
            with self.assertRaises(TimeoutError):
                gate.fetch(url, timeout, "耐心资本")
        with self.assertRaisesRegex(OSError, "host_circuit_open.*repeated_timeout"):
            gate.fetch(url, timeout, "协同出海")
        self.assertEqual(len(called), 2)
        # The next scan gets a fresh circuit and still tests the host.
        self.assertEqual(ScanHostBudget().fetch(url, lambda x: x, "probe"), "probe")

    def test_semantic_failure_does_not_open_network_circuit(self):
        from chinese_journals import ScanHostBudget
        gate = ScanHostBudget()
        def malformed(_):
            raise ValueError("journal_or_issue_not_recognized")
        for _ in range(3):
            with self.assertRaises(ValueError):
                gate.fetch("https://www.ncpssd.cn/journal/details", malformed, None)
        self.assertEqual(gate.blocked, {})

    def test_mobile_fallback_is_catalog_not_publisher(self):
        from chinese_journals import FALLBACKS
        for slug in ("economic_research", "china_industrial", "management_world"):
            kind, url = FALLBACKS[slug]
            self.assertEqual(kind, "catalog")
            self.assertIn("m.ncpssd.cn/journal/details", url)


class CatalogFallbackOnRegressionTests(unittest.TestCase):
    def test_mobile_catalog_used_for_regressed_desktop_issue_without_fake_articles(self):
        from unittest.mock import patch
        import chinese_journals as cj
        desktop = "https://ncpssd.org/journal/details?gch=95499X"
        mobile = "https://m.ncpssd.cn/journal/details?gch=95499X&langType=1&nav=1"
        pages = {
            desktop: b"<html><body>\xe7\xae\xa1\xe7\x90\x86\xe4\xb8\x96\xe7\x95\x8c 2026\xe5\xb9\xb4 \xe7\xac\xac9\xe6\x9c\x9f</body></html>",
            mobile: b"<html><body>\xe7\xae\xa1\xe7\x90\x86\xe4\xb8\x96\xe7\x95\x8c 2026\xe5\xb9\xb4 \xe7\xac\xac11\xe6\x9c\x9f</body></html>",
        }
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "chinese_seen.json").write_text(json.dumps({
                "management_world": {"issue": "2026-10", "articles": [], "baselined": True}
            }), encoding="utf-8")
            with patch.object(cj, "JOURNALS", (("management_world", "管理世界", "catalog", desktop),)), \
                 patch.object(cj, "FALLBACKS", {"management_world": ("catalog", mobile)}):
                result = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda url: pages[url])
            info = result["source_status"]["journals"]["management_world"]
            self.assertEqual(info["issue"], "2026-11")
            self.assertEqual(info["status"], "catalog_only")
            self.assertEqual(info["article_count"], 0)
            self.assertEqual(info["primary_failure"], "stale_primary_index: 2026-09")
            self.assertFalse(result["new_candidates"])
            self.assertEqual(json.loads((folder / "chinese_seen.json").read_text())["management_world"]["issue"], "2026-11")

    def test_fallback_cannot_overwrite_newer_history_with_stale_catalog(self):
        from unittest.mock import patch
        import chinese_journals as cj
        desktop, mobile = "https://ncpssd.org/journal/details?gch=95499X", "https://m.ncpssd.cn/journal/details?gch=95499X"
        pages = {desktop: "<html>管理世界 2026年 第9期</html>".encode(),
                 mobile: "<html>管理世界 2026年 第8期</html>".encode()}
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "chinese_seen.json").write_text(json.dumps({
                "management_world": {"issue": "2026-10", "articles": [], "baselined": True}
            }), encoding="utf-8")
            with patch.object(cj, "JOURNALS", (("management_world", "管理世界", "catalog", desktop),)), \
                 patch.object(cj, "FALLBACKS", {"management_world": ("catalog", mobile)}):
                result = cj.scan_chinese_journals(folder, UTC_NOW, get=lambda url: pages[url])
            info = result["source_status"]["journals"]["management_world"]
            self.assertEqual(info["status"], "stale_index")
            self.assertEqual(info["issue"], "2026-09")
            self.assertEqual(json.loads((folder / "chinese_seen.json").read_text())["management_world"]["issue"], "2026-10")


class IndependentIndexAdapterTests(unittest.TestCase):
    def test_cqvip_issue_evidence_is_issue_only(self):
        import chinese_journals as cj
        html = """<html><body>金融研究 ISSN 1002-7246
            <div>2026 10 9 8 7</div><div>目录 封面 2026年10期 共：12篇</div>
            <a href="/article/12345">错误跳转</a></body></html>""".encode()
        issue, date, rows, count = cj.parse_cqvip_issue(
            html, journal="金融研究", url="https://www.cqvip.com/journal/97926X/97926X")
        self.assertEqual((issue, date, rows, count), ("2026-10", None, [], 12))

    def test_cqvip_wrong_identity_or_navigation_rejected(self):
        import chinese_journals as cj
        good = "https://www.cqvip.com/journal/97926X/97926X"
        for text in ("金融研究 ISSN 1002-5502 目录 2026年10期 共：12篇",
                     "金融研究 ISSN 1002-7246 2026年10期 2026 9 8",
                     "管理世界 ISSN 1002-7246 目录 2026年10期 共：12篇",
                     "金融研究 ISSN 1002-7246 目录 2026年10期 共：0篇"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                cj.parse_cqvip_issue(text.encode(), journal="金融研究", url=good)

    def test_financial_index_recovery_does_not_fake_articles(self):
        import chinese_journals as cj
        from unittest.mock import patch
        primary = "https://www.jryj.org.cn/CN/1002-7246/current.shtml"
        alternate = "https://www.cqvip.com/journal/97926X/97926X"
        def getter(url):
            if url == primary: raise OSError("TLS hostname mismatch")
            if url == alternate:
                return "金融研究 ISSN 1002-7246 目录 封面 2026年10期 共：12篇".encode()
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/"chinese_seen.json").write_text(json.dumps({
                "financial_research":{"issue":"2026-07","articles":[],"baselined":True}
            }),encoding="utf-8")
            with patch.object(cj,"JOURNALS",(("financial_research","金融研究","publisher",primary),)):
                r=cj.scan_chinese_journals(folder,UTC_NOW,get=getter,
                    priority_sources={"financial_research":(("catalog_index",alternate),)})
            j=r["source_status"]["journals"]["financial_research"]
            self.assertEqual(j["issue"],"2026-10")
            self.assertEqual(j["status"],"catalog_only")
            self.assertEqual(j["article_count"],0)
            self.assertEqual(j["article_snapshot"],[])
            self.assertEqual(j["index_claimed_paper_count"],12)
            self.assertEqual(r["new_candidates"],[])
            self.assertEqual(r["source_status"]["records"],0)

    def test_management_regression_independent_source_preserves_ledger(self):
        import chinese_journals as cj
        from unittest.mock import patch
        primary="https://ncpssd.org/journal/details?gch=95499X&langType=1"
        alternate="https://www.cqvip.com/journal/95499X/95499X"
        def getter(url):
            if url==primary:return "管理世界 2026年 第9期".encode()
            if url==alternate:return "管理世界 ISSN 1002-5502 目录 封面 2026年10期 共：18篇".encode()
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/"chinese_seen.json").write_text(json.dumps({
                "management_world":{"issue":"2026-10","articles":["old-identity"],"baselined":True}
            }),encoding="utf-8")
            with patch.object(cj,"JOURNALS",(("management_world","管理世界","catalog",primary),)):
                r=cj.scan_chinese_journals(folder,UTC_NOW,get=getter,
                    priority_sources={"management_world":(("catalog_index",alternate),)})
            j=r["source_status"]["journals"]["management_world"]
            self.assertEqual((j["issue"],j["status"]),("2026-10","catalog_only"))
            self.assertEqual(j["article_count"],0)
            self.assertEqual(r["new_candidates"],[])
            previous=json.loads((folder/"chinese_seen.json").read_text())["management_world"]
            self.assertIn("old-identity",previous["articles"])

    def test_priority_all_outages_keep_previous_and_expose_failure(self):
        import chinese_journals as cj
        from unittest.mock import patch
        primary="https://www.jryj.org.cn/CN/1002-7246/current.shtml"
        alternate="https://www.cqvip.com/journal/97926X/97926X"
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/"chinese_seen.json").write_text(json.dumps({
                "financial_research":{"issue":"2026-10","articles":["old"],"baselined":True}
            }),encoding="utf-8")
            with patch.object(cj,"JOURNALS",(("financial_research","金融研究","publisher",primary),)):
                r=cj.scan_chinese_journals(folder,UTC_NOW,get=lambda url: (_ for _ in ()).throw(TimeoutError(url)),
                    priority_sources={"financial_research":(("catalog_index",alternate),)})
            j=r["source_status"]["journals"]["financial_research"]
            self.assertEqual(j["status"],"failed")
            self.assertEqual(r["new_candidates"],[])
            self.assertEqual(json.loads((folder/"chinese_seen.json").read_text())["financial_research"]["issue"],"2026-10")

    def test_live_official_articles_beat_older_catalog(self):
        import chinese_journals as cj
        primary="https://www.jryj.org.cn/CN/1002-7246/current.shtml"
        alternate="https://www.cqvip.com/journal/97926X/97926X"
        def getter(url):
            if url==primary:
                return ('<html>金融研究 2026年 第10期 '
                        '<a href="/CN/Y2026/V1/I10/11">企业供应链融资与国际专利布局研究</a>'
                        '</html>').encode()
            raise AssertionError("fallback should not be queried")
        kind,url,issue,date,rows,metadata=cj.resolve_priority_sources(
            "financial_research","金融研究","publisher",primary,"2026-09",getter,
            (("catalog_index",alternate),))
        self.assertEqual((kind,url,issue,len(rows)),("publisher",primary,"2026-10",1))
        self.assertNotIn("index_claimed_paper_count",metadata)


class CoverageRootCauseTests(unittest.TestCase):
    """Ponytail: reproduce failures in the actual 2026-11-19 production state."""

    def test_financial_official_http_current_issue_has_real_article_links(self):
        url="http://www.jryj.org.cn/CN/1002-7246/current.shtml"
        page=('<h1>金融研究</h1><div>2026年, 第10期, 总第556期</div>'
              '<a href="/CN/abstract/abstract1662.shtml">银行资产负债结构、放贷能力与货币政策传导效果——基于政府债券增持的视角</a>'
              '<a href="/CN/abstract/abstract1663.shtml">地缘政治风险、跨境供应链与中国企业债券信用利差</a>'
              '<a href="https://evil.example/CN/abstract/abstract9999.shtml">外部注入文章</a>'
              '<a href="/CN/abstract/abstract1661.shtml">下一期其他文章</a>').encode()
        issue, _, rows=cj.parse_toc(page,journal="金融研究",kind="publisher",url=url)
        self.assertEqual(issue,"2026-10")
        self.assertEqual([r["issue"] for r in rows],["2026-10","2026-10"])
        self.assertTrue(all(r["url_scope"]=="article_detail" for r in rows))
        self.assertTrue(all(r["url"].startswith("http://www.jryj.org.cn/") for r in rows))

    def test_financial_official_current_recovers_article_level_without_republishing(self):
        url="http://www.jryj.org.cn/CN/1002-7246/current.shtml"
        page=('<h1>金融研究</h1><p>2026年 第10期</p>'
              '<a href="/CN/abstract/abstract1663.shtml">地缘政治风险、跨境供应链与中国企业债券信用利差</a>').encode()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            (out/"chinese_seen.json").write_text(json.dumps({
                "financial_research":{"issue":"2026-10","articles":[],"baselined":True}
            }))
            with patch.object(cj,"JOURNALS",(("financial_research","金融研究","publisher",url),)):
                r=cj.scan_chinese_journals(out,UTC_NOW,get=lambda _:page,
                                            priority_sources={"financial_research":()})
                journal=r["source_status"]["journals"]["financial_research"]
                self.assertEqual(journal["status"],"ok")
                self.assertEqual(journal["article_link_count"],1)
                self.assertEqual(r["source_status"]["article_level_ok"],1)
                self.assertEqual(len(r["historical_backfill_leads"]),1)
                again=cj.scan_chinese_journals(out,UTC_NOW,get=lambda _:page,
                                                priority_sources={"financial_research":()})
                self.assertEqual(again["historical_backfill_leads"],[])

    def test_current_issue_sufe_does_not_use_mixed_latest_feed(self):
        config={slug:url for slug,_,_,url in cj.JOURNALS}
        self.assertEqual(config["finance_economics"],
                         "https://qks.sufe.edu.cn/J/CJYJ/Article/CurrentIssue/CN")
        # The Latest page includes old issues; never treat every link as current.
        latest=("<h1>财经研究</h1>2026年第09期"
                "<a href='/J/CJYJ/Article/Details/pgbFuTsz-vRzo-GypL-0h9O-AptmzpGperJG'>企业国际知识产权布局与出海</a>"
                "<p>2026年第07期</p>"
                "<a href='/J/CJYJ/Article/Details/aaaa-bbbb-cccc-dddd-eeeeffff0000'>耐心资本与融资约束</a>"
                "<p>2026年第09期</p>").encode()
        _,_,rows=cj.parse_toc(latest,journal="财经研究",kind="publisher",
                              url="https://qks.sufe.edu.cn/J/CJYJ/Article/Latest")
        self.assertEqual(rows[0]["issue"],"2026-07")

    def test_rss_dns_failure_is_visible_but_not_credited_as_missing_official_toc(self):
        url="https://sjjj.magtech.com.cn/CN/home"
        page=('<h1>世界经济</h1><p>2026年,49卷,第11期</p>'
              '<a href="/CN/Y2026/V49/I11/3">政企协同与绿色创新：链长制的硬约束与强牵引</a>').encode()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(cj,"JOURNALS",(("world_economy","世界经济","publisher",url),)):
                r=cj.scan_chinese_journals(Path(tmp),UTC_NOW,get=lambda _:page,
                             rss_get=lambda _: (_ for _ in ()).throw(OSError("CNKI RSS DNS failed")))
            st=r["source_status"]
            self.assertEqual(st["status"],"ok")
            self.assertEqual(st["article_level_ok"],1)
            self.assertEqual(st["rss_health"],"degraded")
            self.assertEqual(st["rss_failed_journals"],["世界经济"])
            self.assertEqual(st["journals"]["world_economy"]["rss"]["status"],"failed")

    def test_catalog_rows_and_mixed_links_are_not_article_level_ok(self):
        catalog="https://ncpssd.org/journal/details.aspx?gch=95645X"
        title_page=('<h1>经济研究</h1><h2>2026年 第9期</h2>'
                    '机器人应用与制造业企业生产链延伸——基于稳链强链视角的考察 '
                    '吴腊梅[1,2];彭水军[3] (25-48)').encode()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(cj,"JOURNALS",(("economic_research","经济研究","catalog",catalog),)):
                r=cj.scan_chinese_journals(Path(tmp),UTC_NOW,get=lambda _:title_page)
            st=r["source_status"]
            self.assertEqual(st["article_level_ok"],0)
            self.assertEqual(st["queries_ok"],1)  # source responded with title rows
            self.assertEqual(st["status"],"degraded")



class IssueOnlyRecoveryTests(unittest.TestCase):
    def test_index_only_then_article_details_same_issue_deliver_backfill_once(self):
        import chinese_journals as cj
        from unittest.mock import patch
        url="https://sjjj.magtech.com.cn/CN/home"
        issue_page="<html><body>世界经济 2026年 第10期</body></html>".encode()
        detail_page=('<html><body>世界经济 2026年 第10期'
                     '<a href="/CN/Y2026/V49/I10/12">长期资本与国际专利国别布局研究</a>'
                     '</body></html>').encode()
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            with patch.object(cj,"JOURNALS",(("world_economy","世界经济","publisher",url),)):
                first=cj.scan_chinese_journals(folder,UTC_NOW,get=lambda _:issue_page)
                self.assertEqual(first["new_candidates"],[])
                self.assertEqual(first["source_status"]["journals"]["world_economy"]["status"],"catalog_only")
                second=cj.scan_chinese_journals(folder,UTC_NOW,get=lambda _:detail_page)
                self.assertEqual(second["new_candidates"],[])
                self.assertEqual(len(second["historical_backfill_leads"]),1)
                lead=second["historical_backfill_leads"][0]
                self.assertEqual(lead["event_type"],"issue_backfill")
                self.assertEqual(lead["issue"],"2026-10")
                self.assertIsNone(lead["published_at"])
                self.assertFalse(lead["date_verified"])
                repeat=cj.scan_chinese_journals(folder,UTC_NOW,get=lambda _:detail_page)
                self.assertEqual(repeat["new_candidates"],[])
                self.assertEqual(repeat["historical_backfill_leads"],[])

    def test_priority_source_full_failure_exposes_each_diagnostic(self):
        import chinese_journals as cj
        from unittest.mock import patch
        url="https://www.jryj.org.cn/CN/1002-7246/current.shtml"
        alt="https://www.cqvip.com/journal/97926X/97926X"
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            with patch.object(cj,"JOURNALS",(("financial_research","金融研究","publisher",url),)):
                result=cj.scan_chinese_journals(folder,UTC_NOW,
                    get=lambda u: (_ for _ in ()).throw(TimeoutError("timed out")),
                    priority_sources={"financial_research":(("catalog_index",alt),)})
            j=result["source_status"]["journals"]["financial_research"]
            self.assertEqual(j["status"],"failed")
            self.assertEqual(len(j["source_attempts"]),2)
            self.assertTrue(all(x["status"]=="failed" for x in j["source_attempts"]))
            self.assertEqual(result["new_candidates"],[])
