import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fork_bootstrap import initialize_fork
from radar import load_research_profile, profile_prefilter, profile_revision, run


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

    def test_existing_scan_cron_and_fork_permission_contract(self):
        root=Path(__file__).resolve().parents[1]
        scan=(root/".github/workflows/scan.yml").read_text(encoding="utf-8")
        self.assertIn("cron: '17 10,22 * * *'",scan)
        self.assertIn("contents: write",scan)
        self.assertIn("cancel-in-progress: false",scan)
        self.assertEqual(scan.count("python fork_bootstrap.py --repository"),1)
        self.assertIn("run: python radar.py --out data",scan)
        self.assertIn("git add data/latest.json data/latest.md data/seen.json data/chinese_seen.json",scan)
        for path in ("pdf-probe.yml","pdf-candidate-acceptance.yml"):
            source=(root/".github/workflows"/path).read_text(encoding="utf-8")
            self.assertNotIn("  schedule:",source)

    def test_invalid_or_wrong_fork_marker_fails_without_touching_ledger(self):
        with tempfile.TemporaryDirectory() as root:
            data=Path(root)
            (data/"seen.json").write_text('{"KEEP":true}')
            for repo in ("", "bad", "/repo", "owner/", "owner/repo/more"):
                with self.assertRaisesRegex(ValueError,"OWNER/REPO"):
                    initialize_fork(repo,data)
            for value in ('{"repository":"other/fork"}', '{"repository":', '[]'):
                (data/"fork_initialized.json").write_text(value)
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    initialize_fork("classmate/radar",data)
                self.assertIn("KEEP", (data/"seen.json").read_text())
            self.assertNotIn("new_fork", (data/"seen.json").read_text())

    def test_second_phase_topic_revision_does_not_silence_or_repeat_old_leads(self):
        profile={"name":"AI与工资","crossref_queries":["ai wages"],
                 "arxiv_queries":[],"keywords":["artificial intelligence","wage"],
                 "min_keyword_hits":2}
        item={"id":"doi:10.1000/ai","title":"Artificial Intelligence and Wage Inequality",
              "abstract":"AI wage inequality","event_at":"2026-11-18",
              "event_type":"crossref_registration","source":"crossref","sources":["crossref"],
              "doi":"10.1000/ai","version":"","url":"https://doi.org/10.1000/ai"}
        queried_since=[]
        def source(since, *, queries=None):
            queried_since.append(since)
            return [item],{"status":"ok","queries_ok":1,"queries_total":1,
                           "records":1,"errors":[]}
        when=datetime(2026,11,19,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as root:
            data=Path(root)
            first=run(data,when,crossref=source,profile=profile)
            self.assertEqual(len(first["new_candidates"]),1)
            self.assertEqual(queried_since[-1],"2026-11-12")
            second=run(data,when,crossref=source,profile=profile)
            self.assertEqual(second["new_candidates"],[])
            self.assertEqual(queried_since[-1],"2026-11-16")
            # Cosmetic rename must not re-emit; real topic/query revision must.
            rename={**profile,"name":"新论文名字"}
            self.assertEqual(profile_revision(profile),profile_revision(rename))
            self.assertEqual(run(data,when,crossref=source,profile=rename)["new_candidates"],[])
            changed={**profile,"crossref_queries":["AI wage and corporate governance"]}
            changed_run=run(data,when,crossref=source,profile=changed)
            self.assertEqual(len(changed_run["new_candidates"]),1)
            self.assertEqual(queried_since[-1],"2026-11-12")
            self.assertNotEqual(first["research_profile"]["revision"],
                                changed_run["research_profile"]["revision"])
            # Reverting to the previous query must not duplicate the original article.
            self.assertEqual(run(data,when,crossref=source,profile=profile)["new_candidates"],[])
            seen=json.loads((data/"seen.json").read_text())
            self.assertTrue(any(key.startswith(profile_revision(profile)+":") for key in seen))
            self.assertTrue(any(key.startswith(profile_revision(changed)+":") for key in seen))

    def test_profile_short_latin_tokens_do_not_match_inside_other_words(self):
        profile={"name":"test","keywords":["ai","wage"],"min_keyword_hits":2}
        assert profile_prefilter({"title":"Fair Wage Statistics","abstract":""},profile)["eligible"] is False
        assert profile_prefilter({"title":"AI Wage Statistics","abstract":""},profile)["eligible"] is True
        assert profile_prefilter({"title":"工资与人工智能发展","abstract":""},
                                 {**profile,"keywords":["工资","人工智能"]})["eligible"] is True

    def test_duplicate_keywords_cannot_satisfy_two_hit_threshold(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"radar_profile.json"
            profile={"name":"wage","crossref_queries":["ai wages"],"arxiv_queries":[],
                     "keywords":["AI","ai"],"min_keyword_hits":2}
            path.write_text(json.dumps(profile),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"duplicate_keywords"):
                load_research_profile(path)

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
