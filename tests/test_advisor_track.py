"""Regression checks for the advisor-aligned P1/P1A literature radar.

Public bibliographic fixture titles only; unpublished manuscript text/data
and institutional access credentials must never enter this repository.
"""
import unittest
from radar import prefilter, QUERIES, PROJECT_CAPS


class AdvisorTrackTests(unittest.TestCase):
    def classify(self, title, abstract=""):
        return prefilter({"title": title, "abstract": abstract})

    def test_entity_list_upstream_supply_detected(self):
        paper = self.classify("US Entity List export controls and foreign supplier relationships")
        self.assertTrue(paper["eligible"])
        self.assertIn(paper["project"], ("P1", "P1A"))

    def test_locational_diversification_resilience_detected(self):
        paper = self.classify("OFDI geographic diversification and global supply chain resilience")
        self.assertTrue(paper["eligible"])
        # P1A intentionally takes precedence for overseas-node + supply papers.
        self.assertIn(paper["project"], ("P1", "P1A"))

    def test_partner_entry_following_foreign_nodes(self):
        paper = self.classify("Foreign subsidiaries and supplier entry after export controls")
        self.assertTrue(paper["eligible"])
        self.assertEqual(paper["project"], "P1A")

    def test_chinese_advisor_theme_detected(self):
        paper = self.classify("实体清单冲击、境外上游供应链韧性与区位多元布局")
        self.assertTrue(paper["eligible"])
        self.assertEqual(paper["project"], "P1")

    def test_avoid_unrelated_export_control_noise(self):
        paper = self.classify("Export control compliance handbook for software license management")
        self.assertFalse(paper["eligible"])

    def test_avoid_generic_fdi_noise(self):
        paper = self.classify("Foreign direct investment and economic growth in small open economies")
        self.assertFalse(paper["eligible"])

    def test_existing_priority_and_limits_preserved(self):
        paper = self.classify("Patient capital and international patent families")
        self.assertEqual(paper["project"], "P0")
        self.assertEqual(PROJECT_CAPS["P0"], 12)
        self.assertEqual(PROJECT_CAPS["P1"], 7)
        self.assertEqual(PROJECT_CAPS["P1A"], 6)

    def test_queries_are_specific_and_nonduplicative(self):
        self.assertEqual(len(QUERIES), len(set(QUERIES)))
        self.assertIn("US entity list export controls foreign supplier relationships", QUERIES)
        self.assertIn("OFDI geographic diversification supply chain resilience", QUERIES)


if __name__ == "__main__":
    unittest.main()
