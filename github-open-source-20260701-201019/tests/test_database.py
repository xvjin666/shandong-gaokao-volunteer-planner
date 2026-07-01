import tempfile
import unittest
from pathlib import Path

from gaokao_decision.database import (
    connect,
    fetch_admissions,
    fetch_score_ranks,
    import_records,
    import_score_rank_records,
    init_db,
    list_batches,
)
from gaokao_decision.importer import load_admissions, load_score_ranks
from gaokao_decision.models import AdmissionRecord, CandidateProfile
from gaokao_decision.recommend import recommend


class DatabaseTests(unittest.TestCase):
    def test_import_and_recommend_from_sqlite(self):
        records = load_admissions("data/sample/admissions_sample.csv")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "gaokao.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                batch_id, report = import_records(connection, records, "data/sample/admissions_sample.csv", "sample")
                saved_records = fetch_admissions(connection)
                batches = list_batches(connection)

        self.assertEqual(batch_id, 1)
        self.assertEqual(report.total_records, len(records))
        self.assertEqual(len(saved_records), len(records))
        self.assertEqual(batches[0]["name"], "sample")

        candidate = CandidateProfile(
            score=610,
            rank=32000,
            subjects=("物理", "化学"),
            interests=("计算机", "电子", "信息"),
            max_tuition=12000,
        )
        recommendations, rejections = recommend(saved_records, candidate, limit=5)
        self.assertGreater(len(recommendations), 0)
        self.assertGreater(len(rejections), 0)

    def test_import_records_rejects_validation_errors_by_default(self):
        records = [
            AdmissionRecord(2025, "test", "", "样例大学", "01", "软件工程", None, 8000, 20)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "gaokao.sqlite"
            with connect(db_path) as connection:
                with self.assertRaises(ValueError):
                    import_records(connection, records, "bad.csv")
                batch_id, report = import_records(connection, records, "bad.csv", strict=False)

        self.assertEqual(batch_id, 1)
        self.assertTrue(report.has_errors)

    def test_import_multi_year_score_ranks_from_open_csv(self):
        records = load_score_ranks("data/sample/score_rank_sample.csv")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "gaokao.sqlite"
            with connect(db_path) as connection:
                batch_id = import_score_rank_records(
                    connection,
                    records,
                    "data/sample/score_rank_sample.csv",
                    "sample_score_ranks",
                )
                saved_records = fetch_score_ranks(connection)

        self.assertEqual(batch_id, 1)
        self.assertEqual(len(saved_records), len(records))
        self.assertEqual(sorted({record.year for record in saved_records}), [2023, 2024, 2025, 2026])


if __name__ == "__main__":
    unittest.main()
