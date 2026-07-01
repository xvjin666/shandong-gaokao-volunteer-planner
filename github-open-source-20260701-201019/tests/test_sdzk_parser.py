from gaokao_decision.sdzk_parser import _extract_subjects, _to_int


def test_sdzk_rank_text_top_50_is_parsed_conservatively():
    assert _to_int("前50") == 50
    assert _to_int("前50名") == 50
    assert _to_int("前 50 名") == 50


def test_sdzk_subject_requirement_variants_are_parsed():
    assert _extract_subjects("软件工程（物理和化学均须选考）") == ("物理", "化学")
    assert _extract_subjects("法学（不限选考科目）") == ("不限",)
    assert _extract_subjects("思想政治教育（思想政治必选）") == ("思想政治",)
