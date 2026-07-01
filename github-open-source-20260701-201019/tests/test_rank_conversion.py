import unittest

from gaokao_decision.importer import load_admissions
from gaokao_decision.models import AdmissionRecord, CandidateProfile, ScoreRankRecord
from gaokao_decision.rank_conversion import build_score_band_plan, score_for_rank


class RankConversionTests(unittest.TestCase):
    def test_score_for_rank_uses_first_cumulative_count_covering_rank(self):
        rows = [
            ScoreRankRecord(2025, "test", 600, 10, 100),
            ScoreRankRecord(2025, "test", 599, 20, 120),
            ScoreRankRecord(2025, "test", 598, 30, 150),
        ]
        self.assertEqual(score_for_rank(rows, 2025, 101).score, 599)
        self.assertEqual(score_for_rank(rows, 2025, 100).score, 600)

    def test_score_band_plan_filters_by_equivalent_score_band(self):
        admissions = load_admissions("data/sample/admissions_sample.csv")
        score_ranks = []
        for year in (2023, 2024, 2025):
            for score, cumulative in [(630, 20000), (610, 32000), (590, 50000)]:
                score_ranks.append(ScoreRankRecord(year, "test", score, 1, cumulative))
        candidate = CandidateProfile(
            score=610,
            rank=32000,
            subjects=("物理", "化学"),
            interests=("计算机", "电子"),
            max_tuition=12000,
        )
        plan = build_score_band_plan(admissions, score_ranks, 32000, candidate, target_size=4, band_width=20)
        self.assertEqual(len(plan.equivalent_scores), 3)
        self.assertEqual(plan.equivalent_scores[0].score, 610)
        self.assertGreater(len(plan.plan.recommendations), 0)

    def test_candidate_pool_respects_interest_filter(self):
        admissions = [
            AdmissionRecord(2025, "test", "A001", "样例大学", "01", "网络空间安全", None, 8000, 10),
            AdmissionRecord(2025, "test", "A002", "样例大学", "02", "心理学", None, 8100, 10),
        ]
        score_ranks = [
            ScoreRankRecord(2025, "test", 650, 1, 8000),
            ScoreRankRecord(2025, "test", 649, 1, 8100),
        ]
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("网络空间安全",),
        )

        plan = build_score_band_plan(admissions, score_ranks, 8000, candidate, target_size=4, band_width=5)

        candidate_names = {item.option_name for item in plan.candidate_recommendations}
        self.assertIn("样例大学 / 网络空间安全", candidate_names)
        self.assertNotIn("样例大学 / 心理学", candidate_names)
        search_names = {item.option_name for item in plan.search_recommendations}
        self.assertIn("样例大学 / 心理学", search_names)

    def test_score_band_plan_adds_rank_relevant_candidates_outside_score_band(self):
        admissions = [
            AdmissionRecord(2025, "test", "A000", "过高大学", "01", "网络空间安全", None, 2000, 10),
            AdmissionRecord(2025, "test", "A001", "带内大学", "01", "网络空间安全", None, 8000, 10),
            AdmissionRecord(2025, "test", "A002", "补充大学", "01", "网络空间安全", None, 12000, 10),
            AdmissionRecord(2025, "test", "A003", "过低大学", "01", "网络空间安全", None, 40000, 10),
        ]
        score_ranks = [
            ScoreRankRecord(2025, "test", 700, 1, 2000),
            ScoreRankRecord(2025, "test", 650, 1, 8000),
            ScoreRankRecord(2025, "test", 610, 1, 12000),
            ScoreRankRecord(2025, "test", 500, 1, 40000),
        ]
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("网络空间安全",),
        )

        plan = build_score_band_plan(admissions, score_ranks, 8000, candidate, target_size=4, band_width=5)

        candidate_names = {item.option_name for item in plan.candidate_recommendations}
        self.assertIn("带内大学 / 网络空间安全", candidate_names)
        self.assertIn("补充大学 / 网络空间安全", candidate_names)
        self.assertNotIn("过高大学 / 网络空间安全", candidate_names)
        self.assertNotIn("过低大学 / 网络空间安全", candidate_names)
        self.assertEqual(plan.score_band_candidate_count, 1)
        self.assertEqual(plan.coverage_guard_added, 1)

    def test_free_search_pool_keeps_full_candidate_set(self):
        admissions = [
            AdmissionRecord(2025, "test", "A000", "过高大学", "01", "网络空间安全", None, 2000, 10),
            AdmissionRecord(2025, "test", "A001", "带内大学", "01", "网络空间安全", None, 8000, 10),
            AdmissionRecord(2025, "test", "A002", "补充大学", "01", "网络空间安全", None, 12000, 10),
            AdmissionRecord(2025, "test", "A003", "过低大学", "01", "网络空间安全", None, 40000, 10),
            AdmissionRecord(2025, "test", "A004", "自由检索大学", "01", "心理学", None, 8100, 10),
        ]
        score_ranks = [
            ScoreRankRecord(2025, "test", 700, 1, 2000),
            ScoreRankRecord(2025, "test", 650, 1, 8000),
            ScoreRankRecord(2025, "test", 649, 1, 8100),
            ScoreRankRecord(2025, "test", 610, 1, 12000),
            ScoreRankRecord(2025, "test", 500, 1, 40000),
        ]
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("网络空间安全",),
        )

        plan = build_score_band_plan(admissions, score_ranks, 8000, candidate, target_size=4, band_width=5)

        regular_names = {item.option_name for item in plan.candidate_recommendations}
        search_names = {item.option_name for item in plan.search_recommendations}
        self.assertNotIn("过高大学 / 网络空间安全", regular_names)
        self.assertNotIn("过低大学 / 网络空间安全", regular_names)
        self.assertIn("过高大学 / 网络空间安全", search_names)
        self.assertIn("过低大学 / 网络空间安全", search_names)
        self.assertNotIn("自由检索大学 / 心理学", regular_names)
        self.assertIn("自由检索大学 / 心理学", search_names)

    def test_custom_score_gaps_change_generated_risk_bands(self):
        admissions = [
            AdmissionRecord(2025, "test", "A001", "样例大学", "01", "网络空间安全", None, 9300, 10),
        ]
        score_ranks = []
        for year in (2025, 2026):
            score_ranks.extend([
                ScoreRankRecord(year, "test", 612, 1, 8500),
                ScoreRankRecord(year, "test", 606, 1, 9300),
                ScoreRankRecord(year, "test", 600, 1, 10000),
                ScoreRankRecord(year, "test", 594, 1, 12000),
                ScoreRankRecord(year, "test", 588, 1, 14000),
                ScoreRankRecord(year, "test", 576, 1, 18000),
            ])
        candidate = CandidateProfile(
            score=0,
            rank=10000,
            subjects=("物理", "化学", "生物"),
            interests=("网络空间安全",),
        )
        quotas = {"高冲": 1, "冲": 1, "稳中偏冲": 0, "稳": 0, "保": 0, "强保": 0}

        wide = build_score_band_plan(
            admissions,
            score_ranks,
            10000,
            candidate,
            strategy="custom",
            target_size=2,
            band_width=20,
            custom_quotas=quotas,
            custom_risk_gaps={"challenge": 12, "steady": 12, "safe": 12},
        )
        narrow = build_score_band_plan(
            admissions,
            score_ranks,
            10000,
            candidate,
            strategy="custom",
            target_size=2,
            band_width=20,
            custom_quotas=quotas,
            custom_risk_gaps={"challenge": 4, "steady": 12, "safe": 12},
        )

        self.assertEqual(wide.candidate_recommendations[0].risk_band, "冲")
        self.assertEqual(narrow.candidate_recommendations[0].risk_band, "高冲")


if __name__ == "__main__":
    unittest.main()
