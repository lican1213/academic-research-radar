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
            "doi": item["doi"], "version": "", "last_seen": "2025-01-01"
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


if __name__ == "__main__":
    unittest.main()
