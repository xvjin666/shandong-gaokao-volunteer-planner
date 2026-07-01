import unittest

from gaokao_decision.importer import load_admissions
from gaokao_decision.models import AdmissionRecord, CandidateProfile
from gaokao_decision.recommend import recommend
from gaokao_decision.scoring import classify_risk, hard_filter, success_probability


class RecommenderTests(unittest.TestCase):
    def test_risk_bands_are_rank_based(self):
        self.assertEqual(classify_risk(32000, 30500)[0], "冲")
        self.assertEqual(classify_risk(32000, 34000)[0], "稳中偏冲")
        self.assertEqual(classify_risk(32000, 48000)[0], "保")
        self.assertEqual(classify_risk(1, 120)[0], "稳")

    def test_custom_risk_thresholds_change_risk_band(self):
        wide_thresholds = (1200, 0, 500, 1500, 3000)
        narrow_thresholds = (300, 0, 500, 1500, 3000)

        self.assertEqual(classify_risk(10000, 9300, wide_thresholds)[0], "冲")
        self.assertEqual(classify_risk(10000, 9300, narrow_thresholds)[0], "高冲")

    def test_success_probability_is_capped_by_risk_band(self):
        band, _, _ = classify_risk(9100, 4000)
        probability = success_probability(9100, 4000, band, fit=1.0, stability=1.0)
        self.assertEqual(band, "高冲")
        self.assertLessEqual(probability, 0.18)
        self.assertLess(probability, 0.50)

        steady_band, _, _ = classify_risk(9100, 9800)
        steady_probability = success_probability(9100, 9800, steady_band, fit=0.6, stability=0.8)
        self.assertEqual(steady_band, "稳中偏冲")
        self.assertGreaterEqual(steady_probability, 0.38)
        self.assertLessEqual(steady_probability, 0.60)

    def test_recommendations_include_evidence_and_falsification_tests(self):
        records = load_admissions("data/sample/admissions_sample.csv")
        candidate = CandidateProfile(
            score=610,
            rank=32000,
            subjects=("物理", "化学"),
            interests=("计算机", "电子", "信息"),
            max_tuition=12000,
        )
        recommendations, rejections = recommend(records, candidate, limit=5)

        self.assertGreater(len(recommendations), 0)
        self.assertTrue(recommendations[0].evidence)
        self.assertTrue(recommendations[0].falsification_tests)
        self.assertTrue(any("中外合作" in reason for rejection in rejections for reason in rejection.reasons))

    def test_subject_filter_rejects_missing_required_subject(self):
        records = load_admissions("data/sample/admissions_sample.csv")
        candidate = CandidateProfile(
            score=610,
            rank=32000,
            subjects=("历史", "地理"),
            interests=("计算机",),
            max_tuition=12000,
        )
        recommendations, rejections = recommend(records, candidate, limit=10)
        self.assertEqual(len(recommendations), 0)
        self.assertGreater(len(rejections), 0)

    def test_interest_filter_matches_major_not_school_name(self):
        records = load_admissions("data/sample/admissions_sample.csv")
        candidate = CandidateProfile(
            score=610,
            rank=32000,
            subjects=("物理", "化学", "生物"),
            interests=("金融",),
            max_tuition=12000,
        )
        recommendations, _ = recommend(records, candidate, limit=10)
        self.assertTrue(recommendations)
        self.assertTrue(all("财经" in item.option_name or "金融" in item.option_name for item in recommendations))

    def test_experimental_class_must_expose_specific_professional_direction(self):
        math_record = AdmissionRecord(
            year=2025,
            source_id="test",
            school_code="A001",
            school_name="样例大学",
            major_code="01",
            major_name="理科试验班类(数学与统计)",
            min_score=None,
            min_rank=120,
        )
        humanities_record = AdmissionRecord(
            year=2025,
            source_id="test",
            school_code="A002",
            school_name="样例大学",
            major_code="02",
            major_name="文科试验班类(文科基础类专业)",
            min_score=None,
            min_rank=120,
        )
        candidate = CandidateProfile(
            score=0,
            rank=1,
            subjects=("物理", "化学", "生物"),
            interests=("网络空间安全",),
        )
        math_candidate = CandidateProfile(
            score=0,
            rank=1,
            subjects=("物理", "化学", "生物"),
            interests=("数学",),
        )

        self.assertIsNotNone(hard_filter([math_record], candidate))
        self.assertIsNone(hard_filter([math_record], math_candidate))
        self.assertIsNotNone(hard_filter([humanities_record], candidate))

    def test_interest_hard_filter_uses_direct_professional_tags_only(self):
        statistics_record = AdmissionRecord(
            year=2025,
            source_id="test",
            school_code="A001",
            school_name="样例大学",
            major_code="01",
            major_name="统计学",
            min_score=None,
            min_rank=120,
        )
        medicine_record = AdmissionRecord(
            year=2025,
            source_id="test",
            school_code="A002",
            school_name="样例大学",
            major_code="02",
            major_name="临床医学",
            min_score=None,
            min_rank=120,
        )
        candidate = CandidateProfile(
            score=0,
            rank=1,
            subjects=("物理", "化学", "生物"),
            interests=("计算机",),
        )

        self.assertIsNotNone(hard_filter([statistics_record], candidate))
        self.assertIsNotNone(hard_filter([medicine_record], candidate))

    def test_computer_tag_keeps_official_computer_category_majors(self):
        accepted_major_names = [
            "计算机科学与技术",
            "软件工程",
            "网络工程",
            "物联网工程",
            "数据科学与大数据技术",
            "网络空间安全",
        ]
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("计算机",),
        )

        for index, major_name in enumerate(accepted_major_names, 1):
            with self.subTest(major_name=major_name):
                record = AdmissionRecord(
                    2025,
                    "test",
                    f"A{index:03d}",
                    "样例大学",
                    f"{index:02d}",
                    major_name,
                    None,
                    8000 + index,
                    20,
                )
                self.assertIsNone(hard_filter([record], candidate))

    def test_math_tag_does_not_admit_computer_science_by_related_family(self):
        record = AdmissionRecord(
            2025,
            "test",
            "A001",
            "样例大学",
            "01",
            "计算机科学与技术",
            None,
            8000,
            20,
        )
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("数学",),
        )

        self.assertIsNotNone(hard_filter([record], candidate))

    def test_same_major_with_changed_annual_codes_is_merged(self):
        records = [
            AdmissionRecord(2023, "test", "A422", "山东大学", "Z5", "网络空间安全", None, 7509, 75),
            AdmissionRecord(2024, "test", "A422", "山东大学", "ZT", "网络空间安全", None, 8041, 95),
            AdmissionRecord(2025, "test", "A422", "山东大学", "Y8", "网络空间安全", None, 7974, 96),
            AdmissionRecord(2023, "test", "A422", "山东大学", "Y8", "能源动力类", None, 10131, 60),
        ]
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("网络空间安全",),
        )

        recommendations, _ = recommend(records, candidate, limit=10)
        network_recommendations = [
            item for item in recommendations if item.option_name == "山东大学 / 网络空间安全"
        ]

        self.assertEqual(len(network_recommendations), 1)
        self.assertEqual(
            [point.year for point in network_recommendations[0].evidence],
            [2023, 2024, 2025],
        )
        self.assertTrue(all(point.min_rank != 10131 for point in network_recommendations[0].evidence))

    def test_near_three_year_history_supplements_changed_parenthetical_names(self):
        records = [
            AdmissionRecord(2023, "test", "A003", "清华大学", "1B", "文科试验班类(通用基础类)", None, 4, 1),
            AdmissionRecord(2024, "test", "A003", "清华大学", "1B", "文科试验班类(通用基础类)", None, 50, 2),
            AdmissionRecord(2025, "test", "A003", "清华大学", "1C", "文科试验班类(文科各专业)", None, 50, 3),
        ]
        candidate = CandidateProfile(
            score=0,
            rank=10,
            subjects=("物理", "化学", "生物"),
            interests=("汉语言文学",),
        )

        recommendations, _ = recommend(records, candidate, limit=10)
        item = next(
            recommendation
            for recommendation in recommendations
            if recommendation.option_name == "清华大学 / 文科试验班类(文科各专业)"
        )

        self.assertEqual([point.year for point in item.evidence], [2023, 2024, 2025])
        self.assertEqual([point.min_rank for point in item.evidence], [4, 50, 50])

    def test_generic_engineering_experimental_classes_are_not_over_merged(self):
        records = [
            AdmissionRecord(2024, "test", "A001", "样例大学", "01", "工科试验班(机器人方向)", None, 1000, 10),
            AdmissionRecord(2025, "test", "A001", "样例大学", "02", "工科试验班(空天方向)", None, 2000, 10),
        ]
        candidate = CandidateProfile(
            score=0,
            rank=1500,
            subjects=("物理", "化学", "生物"),
        )

        recommendations, _ = recommend(records, candidate, limit=10)
        by_name = {item.option_name: item for item in recommendations}

        self.assertEqual(len(by_name["样例大学 / 工科试验班(机器人方向)"].evidence), 1)
        self.assertEqual(len(by_name["样例大学 / 工科试验班(空天方向)"].evidence), 1)

    def test_network_security_interest_is_narrow_not_math_or_chemistry(self):
        network_record = AdmissionRecord(
            2025, "test", "A001", "样例大学", "01", "信息安全", None, 8000, 30
        )
        math_record = AdmissionRecord(
            2025, "test", "A002", "样例大学", "02", "数学与应用数学", None, 8200, 20
        )
        chemistry_record = AdmissionRecord(
            2025, "test", "A003", "样例大学", "03", "应用化学", None, 8300, 20
        )
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("网络空间安全",),
        )

        recommendations, rejections = recommend(
            [network_record, math_record, chemistry_record],
            candidate,
            limit=10,
        )

        self.assertEqual([item.option_name for item in recommendations], ["样例大学 / 信息安全"])
        rejected_names = {item.option_name for item in rejections}
        self.assertIn("样例大学 / 数学与应用数学", rejected_names)
        self.assertIn("样例大学 / 应用化学", rejected_names)

    def test_cyber_interest_matches_computer_category_network_security_direction(self):
        record = AdmissionRecord(
            2025,
            "test",
            "A701",
            "西安电子科技大学",
            "2B",
            "计算机类(网络安全)",
            None,
            9584,
            16,
        )

        for interest in ("网络空间安全", "信息安全"):
            with self.subTest(interest=interest):
                candidate = CandidateProfile(
                    score=0,
                    rank=10000,
                    subjects=("物理", "化学", "生物"),
                    interests=(interest,),
                )
                self.assertIsNone(hard_filter([record], candidate))

    def test_standard_major_name_matches_shandong_admission_category(self):
        computer_category_record = AdmissionRecord(
            2025,
            "test",
            "A701",
            "西安电子科技大学",
            "2B",
            "计算机类(网络安全)",
            None,
            9584,
            16,
        )
        electronic_category_record = AdmissionRecord(
            2025,
            "test",
            "A702",
            "样例大学",
            "3C",
            "电子信息类(通信)",
            None,
            12000,
            20,
        )
        math_record = AdmissionRecord(
            2025,
            "test",
            "A703",
            "样例大学",
            "4D",
            "数学与应用数学",
            None,
            13000,
            20,
        )

        computer_candidate = CandidateProfile(
            score=0,
            rank=10000,
            subjects=("物理", "化学", "生物"),
            interests=("计算机科学与技术",),
        )
        electronic_candidate = CandidateProfile(
            score=0,
            rank=10000,
            subjects=("物理", "化学", "生物"),
            interests=("电子信息工程",),
        )

        self.assertIsNone(hard_filter([computer_category_record], computer_candidate))
        self.assertIsNone(hard_filter([electronic_category_record], electronic_candidate))
        self.assertIsNotNone(hard_filter([math_record], computer_candidate))

    def test_elite_rank_prioritizes_top_school_selectivity_within_same_band(self):
        records = [
            AdmissionRecord(2025, "test", "A001", "清华大学", "01", "软件工程", None, 120, 10),
            AdmissionRecord(2023, "test", "B001", "普通样例大学", "01", "软件工程", None, 179, 30),
            AdmissionRecord(2024, "test", "B001", "普通样例大学", "01", "软件工程", None, 180, 30),
            AdmissionRecord(2025, "test", "B001", "普通样例大学", "01", "软件工程", None, 181, 30),
        ]
        candidate = CandidateProfile(
            score=0,
            rank=1,
            subjects=("物理", "化学", "生物"),
            interests=("软件",),
        )

        recommendations, _ = recommend(records, candidate, limit=10)

        self.assertEqual(recommendations[0].option_name, "清华大学 / 软件工程")
        self.assertEqual(recommendations[0].risk_band, recommendations[1].risk_band)

    def test_context_exclusions_prevent_direction_words_from_overriding_major_family(self):
        ecommerce_record = AdmissionRecord(
            2025, "test", "A001", "样例大学", "01", "电子商务(大数据决策分析)", None, 8000, 30
        )
        math_with_software_record = AdmissionRecord(
            2025, "test", "A002", "样例大学", "02", "数学与应用数学(含软件设计方向)", None, 8200, 30
        )

        default_info_candidate = CandidateProfile(
            0,
            8000,
            ("物理", "化学", "生物"),
            ("计算机", "软件", "人工智能", "电子", "自动化"),
        )
        cyber_candidate = CandidateProfile(
            0,
            8000,
            ("物理", "化学", "生物"),
            ("网络空间安全",),
        )

        self.assertIsNotNone(hard_filter([ecommerce_record], default_info_candidate))
        self.assertIsNotNone(hard_filter([math_with_software_record], cyber_candidate))

    def test_default_information_interests_do_not_match_psychology(self):
        psychology_record = AdmissionRecord(
            2025, "test", "A001", "样例大学", "01", "心理学", None, 8000, 30
        )
        software_record = AdmissionRecord(
            2025, "test", "A002", "样例大学", "02", "软件工程", None, 8200, 20
        )
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("计算机", "软件", "人工智能", "电子", "自动化"),
        )

        recommendations, rejections = recommend(
            [psychology_record, software_record],
            candidate,
            limit=10,
        )

        self.assertEqual([item.option_name for item in recommendations], ["样例大学 / 软件工程"])
        self.assertIn("样例大学 / 心理学", {item.option_name for item in rejections})

    def test_short_interest_words_use_domain_specific_direct_matches(self):
        ecommerce_record = AdmissionRecord(
            2025, "test", "A001", "样例大学", "01", "电子商务", None, 8000, 30
        )
        circuit_design_record = AdmissionRecord(
            2025, "test", "A002", "样例大学", "02", "集成电路设计与集成系统", None, 8200, 20
        )
        visual_design_record = AdmissionRecord(
            2025, "test", "A003", "样例大学", "03", "视觉传达设计", None, 8300, 20
        )
        animal_medicine_record = AdmissionRecord(
            2025, "test", "A004", "样例大学", "04", "动物医学", None, 8400, 20
        )
        clinical_record = AdmissionRecord(
            2025, "test", "A005", "样例大学", "05", "临床医学", None, 8500, 20
        )

        self.assertIsNotNone(hard_filter([ecommerce_record], CandidateProfile(0, 8000, ("物理", "化学", "生物"), ("电子",))))
        self.assertIsNotNone(hard_filter([circuit_design_record], CandidateProfile(0, 8000, ("物理", "化学", "生物"), ("设计",))))
        self.assertIsNone(hard_filter([visual_design_record], CandidateProfile(0, 8000, ("物理", "化学", "生物"), ("设计",))))
        self.assertIsNotNone(hard_filter([animal_medicine_record], CandidateProfile(0, 8000, ("物理", "化学", "生物"), ("医学",))))
        self.assertIsNone(hard_filter([clinical_record], CandidateProfile(0, 8000, ("物理", "化学", "生物"), ("医学",))))

    def test_expanded_interest_labels_match_their_own_domains_only(self):
        cases = [
            ("小语种", "俄语", "临床医学"),
            ("体育运动", "运动康复", "软件工程"),
            ("矿业资源", "资源勘查工程", "心理学"),
            ("食品酿造", "酿酒工程", "电子商务"),
            ("航空飞行", "飞行技术", "心理学"),
            ("仪器测控", "测控技术与仪器", "口腔医学"),
            ("文化遗产", "非物质文化遗产保护", "软件工程"),
            ("会展传播", "会展经济与管理", "临床医学"),
            ("采购零售", "采购管理", "应用化学"),
            ("中医药细分", "中医养生学", "临床医学"),
        ]
        for interest, accepted_major, rejected_major in cases:
            with self.subTest(interest=interest):
                accepted = AdmissionRecord(
                    2025, "test", "A001", "样例大学", "01", accepted_major, None, 8000, 30
                )
                rejected = AdmissionRecord(
                    2025, "test", "A002", "样例大学", "02", rejected_major, None, 8200, 30
                )
                candidate = CandidateProfile(
                    0,
                    8000,
                    ("物理", "化学", "生物"),
                    (interest,),
                )

                self.assertIsNone(hard_filter([accepted], candidate))
                self.assertIsNotNone(hard_filter([rejected], candidate))

    def test_school_specific_trial_class_overrides_are_related_not_universal(self):
        tsinghua_science = AdmissionRecord(
            2025, "test", "A003", "清华大学", "1B", "理科试验班(理科各专业)", None, 100, 3
        )
        pku_liberal = AdmissionRecord(
            2025, "test", "A001", "北京大学", "17", "文科试验班类(不限选考科目类专业)", None, 100, 3
        )
        bit_elite = AdmissionRecord(
            2025, "test", "A007", "北京理工大学", "02", "工科试验班(徐特立英才班)", None, 100, 3
        )

        self.assertIsNone(hard_filter(
            [tsinghua_science],
            CandidateProfile(0, 1, ("物理", "化学", "生物"), ("数学",)),
        ))
        self.assertIsNotNone(hard_filter(
            [tsinghua_science],
            CandidateProfile(0, 1, ("物理", "化学", "生物"), ("网络空间安全",)),
        ))
        self.assertIsNone(hard_filter(
            [pku_liberal],
            CandidateProfile(0, 1, ("历史", "地理", "思想政治"), ("法学",)),
        ))
        self.assertIsNone(hard_filter(
            [bit_elite],
            CandidateProfile(0, 1, ("物理", "化学", "生物"), ("航空航天",)),
        ))

    def test_same_major_same_year_duplicate_codes_are_not_merged(self):
        records = [
            AdmissionRecord(2025, "test", "A145", "东北大学", "1Q", "计算机类", None, 8319, 7, tags=("计算机",)),
            AdmissionRecord(2025, "test", "A145", "东北大学", "1T", "计算机类", None, 10528, 20, tags=("计算机",)),
        ]
        candidate = CandidateProfile(
            score=0,
            rank=9000,
            subjects=("物理", "化学", "生物"),
            interests=("计算机",),
        )

        recommendations, _ = recommend(records, candidate, limit=10)

        self.assertEqual(
            len([item for item in recommendations if item.option_name == "东北大学 / 计算机类"]),
            2,
        )

    def test_school_level_filters_are_hard_filters(self):
        records = [
            AdmissionRecord(2025, "test", "A422", "山东大学", "01", "软件工程", None, 8000, 20),
            AdmissionRecord(2025, "test", "A001", "济南大学", "01", "软件工程", None, 8200, 20),
        ]
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("软件",),
            require_985=True,
        )

        recommendations, rejections = recommend(records, candidate, limit=10)

        self.assertEqual([item.option_name for item in recommendations], ["山东大学 / 软件工程"])
        self.assertIn("济南大学 / 软件工程", {item.option_name for item in rejections})

    def test_public_undergraduate_filter_rejects_known_private_schools(self):
        private_record = AdmissionRecord(
            2025, "test", "D998", "齐鲁理工学院", "01", "软件工程", None, 8000, 20
        )
        public_record = AdmissionRecord(
            2025, "test", "A422", "山东大学", "01", "软件工程", None, 8200, 20
        )
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("软件",),
            require_public_undergraduate=True,
        )

        recommendations, rejections = recommend([private_record, public_record], candidate, limit=10)

        self.assertEqual([item.option_name for item in recommendations], ["山东大学 / 软件工程"])
        self.assertIn("齐鲁理工学院 / 软件工程", {item.option_name for item in rejections})

    def test_private_schools_are_rejected_unless_explicitly_allowed(self):
        private_record = AdmissionRecord(
            2025, "test", "D998", "齐鲁理工学院", "01", "软件工程", None, 8000, 20
        )
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("软件",),
        )

        self.assertIsNotNone(hard_filter([private_record], candidate))
        self.assertIsNone(hard_filter([private_record], CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("软件",),
            allow_private=True,
        )))

    def test_sino_foreign_and_high_fee_variants_are_rejected(self):
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            interests=("软件",),
        )
        records = [
            AdmissionRecord(2025, "test", "A001", "样例大学", "01", "软件工程(中外合作办学)", None, 8000, 20),
            AdmissionRecord(2025, "test", "A002", "样例大学", "02", "软件工程", None, 8000, 20, school_type="中外合作办学"),
            AdmissionRecord(2025, "test", "A003", "样例大学", "03", "软件工程", None, 8000, 20, school_type="高收费"),
        ]

        for record in records:
            with self.subTest(record=record.option_name):
                rejection = hard_filter([record], candidate)
                self.assertIsNotNone(rejection)
                self.assertIn("中外合作/高收费", rejection.reasons[0])

    def test_composite_subject_requirement_is_split_before_filtering(self):
        record = AdmissionRecord(
            2025,
            "test",
            "A001",
            "样例大学",
            "01",
            "软件工程",
            None,
            8000,
            20,
            subjects=("物理和化学",),
        )

        self.assertIsNone(hard_filter([record], CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
        )))
        rejection = hard_filter([record], CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "生物", "地理"),
        ))
        self.assertIsNotNone(rejection)
        self.assertIn("化学", rejection.reasons[0])

    def test_unknown_subjects_can_be_strictly_rejected(self):
        record = AdmissionRecord(
            2025, "test", "A001", "样例大学", "01", "软件工程", None, 8000, 20
        )
        candidate = CandidateProfile(
            score=0,
            rank=8000,
            subjects=("物理", "化学", "生物"),
            require_known_subjects=True,
        )

        rejection = hard_filter([record], candidate)
        self.assertIsNotNone(rejection)
        self.assertIn("缺少选科要求", rejection.reasons[0])


if __name__ == "__main__":
    unittest.main()
