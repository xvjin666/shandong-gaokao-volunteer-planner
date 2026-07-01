import unittest

from gaokao_decision.importer import load_admissions
from gaokao_decision.models import CandidateProfile
from gaokao_decision.plan import build_volunteer_plan


class PlanTests(unittest.TestCase):
    def test_balanced_plan_has_counts_and_evidence(self):
        records = load_admissions("data/sample/admissions_sample.csv")
        candidate = CandidateProfile(
            score=610,
            rank=32000,
            subjects=("物理", "化学"),
            interests=("计算机", "电子", "信息"),
            max_tuition=12000,
        )
        plan = build_volunteer_plan(records, candidate, strategy="balanced", target_size=3)

        self.assertEqual(plan.strategy, "balanced")
        self.assertEqual(len(plan.recommendations), 3)
        self.assertGreater(sum(plan.risk_counts.values()), 0)
        self.assertTrue(plan.recommendations[0].evidence)


if __name__ == "__main__":
    unittest.main()
