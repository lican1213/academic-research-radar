import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fork_bootstrap import initialize_fork
from radar import load_research_profile, profile_prefilter, run, prefilter


class ForkSetupTests(unittest.TestCase):
    def test_source_repository_never_resets_ledgers(self):
        with tempfile.TemporaryDirectory() as root:
            data=Path(root)
            (data/"seen.json").write_text('{"KEEP":{"emitted":true}}')
            self.assertEqual(initialize_fork("lican1213/academic-research-radar", data),
                             "upstream_unchanged")
            self.assertIn("KEEP", (data/"seen.json").read_text())
            self.assertFalse((data/"fork_initialized.json").exists())

    def test_fork_clears_inherited_state_exactly_once(self):
        with tempfile.TemporaryDirectory() as root:
            data=Path(root)
            (data/"seen.json").write_text('{"OLD_UPSTREAM":true}')
            (data/"chinese_seen.json").write_text('{"P0":true}')
            (data/"latest.json").write_text('{"status":"ok","generated_at":"old"}')
            self.assertEqual(initialize_fork("classmate/radar", data),
                             "new_fork_initialized")
            self.assertEqual(json.loads((data/"seen.json").read_text()), {})
            self.assertEqual(json.loads((data/"chinese_seen.json").read_text()), {})
            self.assertIsNone(json.loads((data/"latest.json").read_text())["generated_at"])
            (data/"seen.json").write_text('{"NEW":{"emitted":true}}')
            self.assertEqual(initialize_fork("classmate/radar", data),
                             "already_initialized")
            self.assertIn("NEW", (data/"seen.json").read_text())
            self.assertEqual(json.loads((data/"fork_initialized.json").read_text())["repository"],
                             "classmate/radar")

    def test_profile_opt_in_load_and_validation(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"radar_profile.json"
            self.assertIsNone(load_research_profile(path))
            sample={"name":"AI与工资","crossref_queries":["ai wage inequality"],
                    "arxiv_queries":[],"keywords":["AI","wage inequality"],
                    "min_keyword_hits":2}
            path.write_text(json.dumps(sample,ensure_ascii=False))
            obj=load_research_profile(path)
            self.assertEqual(obj["name"],"AI与工资")
            self.assertEqual(obj["arxiv_queries"],[])
            sample["min_keyword_hits"]=3
            path.write_text(json.dumps(sample,ensure_ascii=False))
            with self.assertRaisesRegex(ValueError,"min_keyword_hits"):
                load_research_profile(path)

    def test_custom_topic_prevents_upstream_p0_classification(self):
        profile={"name":"AI与工资","crossref_queries":["ai wages"],
                 "arxiv_queries":[],"keywords":["artificial intelligence","wage"],
                 "min_keyword_hits":2}
        candidate={"id":"doi:10.1000/ai","title":"Artificial Intelligence and Wage Inequality",
                   "abstract":"A study of firm pay","event_at":"2026-11-18",
                   "event_type":"crossref_registration",
                   "source":"crossref","sources":["crossref"],"doi":"10.1000/ai",
                   "version":"","url":"https://doi.org/10.1000/ai"}
        self.assertEqual(profile_prefilter(candidate,profile)["project"],"RESEARCH")
        self.assertTrue(profile_prefilter(candidate,profile)["eligible"])
        self.assertFalse(profile_prefilter(
            {**candidate,"title":"Patent Families and Technology","abstract":"Firm size"},profile
        )["eligible"])

        captured=[]
        def fake_crossref(since, *, queries=None):
            captured.extend(queries or [])
            return [candidate],{"status":"ok","queries_ok":1,"queries_total":1,
                                "records":1,"errors":[]}
        with tempfile.TemporaryDirectory() as root:
            report=run(Path(root),datetime(2026,11,19,tzinfo=timezone.utc),
                       crossref=fake_crossref, profile=profile)
            self.assertEqual(report["research_profile"]["name"],"AI与工资")
            self.assertEqual(report["new_candidates"][0]["project"],"RESEARCH")
            self.assertEqual(report["new_candidates"][0]["title"],candidate["title"])
            self.assertNotIn("arxiv",report["source_status"])
            self.assertEqual(captured,["ai wages"])
            follow=run(Path(root),datetime(2026,11,19,tzinfo=timezone.utc),
                       crossref=fake_crossref,profile=profile)
            self.assertEqual(follow["new_candidates"],[])


if __name__ == "__main__":
    unittest.main()
