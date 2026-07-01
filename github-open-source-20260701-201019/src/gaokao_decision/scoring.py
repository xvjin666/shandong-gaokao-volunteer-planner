from __future__ import annotations

import json
import os
import csv
from pathlib import Path
from statistics import mean

from .models import AdmissionRecord, CandidateProfile, EvidencePoint, Rejection
from .school_profiles import is_public_undergraduate, school_tags


INTEREST_MAJOR_MAP_VERSION = "interest-major-map-v1"
INTEREST_MAJOR_MAP_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "processed" / "interest_major_map.json"
)
INTEREST_SCHOOL_MAJOR_MAP_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "curated" / "interest_school_major_overrides.csv"
)
UNDERGRADUATE_MAJOR_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "processed" / "undergraduate_majors_2026.json"
)

INTEREST_LABELS = (
    "计算机", "软件", "人工智能", "数据科学", "网络空间安全", "信息安全",
    "电子", "电子信息", "通信工程", "集成电路", "微电子", "物联网", "智能科学",
    "自动化", "机器人工程", "仪器测控",
    "机械", "电气", "车辆工程", "航空航天", "航空飞行", "船舶", "兵器", "土木", "建筑环境",
    "交通", "能源", "新能源", "材料", "冶金", "测绘", "矿业资源", "水利", "环境工程", "安全工程",
    "数学", "统计", "物理", "应用物理", "化学", "应用化学", "生物科学", "地理科学",
    "大气科学", "海洋科学", "地质学", "生态学", "心理学",
    "医学", "临床医学", "口腔医学", "基础医学", "预防医学", "中医学", "中医药细分", "药学",
    "医学影像", "医学检验", "护理学", "康复治疗", "生物医学工程",
    "金融", "经济学", "财政学", "税收学", "会计学", "财务管理", "审计学",
    "工商管理", "市场营销", "人力资源", "物流管理", "会展传播", "采购零售", "信息管理与信息系统",
    "数据管理", "电子商务", "国际经济与贸易",
    "法学", "知识产权", "政治学", "思想政治教育", "社会学", "社会工作",
    "公共管理", "行政管理", "公安学", "马克思主义理论",
    "师范", "教育学", "学前教育", "小学教育", "汉语言文学", "外国语言文学", "英语", "小语种",
    "新闻传播", "广告学", "网络与新媒体", "编辑出版", "播音主持",
    "设计", "工业设计", "数字媒体", "动画", "美术学", "音乐学", "戏剧影视",
    "建筑学", "城乡规划", "风景园林", "服装设计",
    "体育运动", "农学", "植物保护", "园艺", "动物医学", "动物科学", "林学", "水产",
    "食品科学", "食品质量", "草业科学",
    "食品酿造", "历史学", "考古学", "文化遗产", "哲学", "档案学", "图书情报",
    "文化产业管理", "旅游管理", "酒店管理",
)


YEAR_WEIGHTS = {
    2025: 0.50,
    2024: 0.30,
    2023: 0.20,
}


def hard_filter(records: list[AdmissionRecord], candidate: CandidateProfile) -> Rejection | None:
    latest = max(records, key=lambda item: item.year)
    reasons: list[str] = []

    if latest.subjects and "不限" not in latest.subjects:
        selected_subjects = {_normalize_subject(subject) for subject in candidate.subjects}
        required_subjects = _required_subjects(latest.subjects)
        missing = [subject for subject in required_subjects if subject not in selected_subjects]
        if missing:
            reasons.append(f"选科不满足：要求 {'/'.join(required_subjects)}")
    elif candidate.require_known_subjects:
        reasons.append("缺少选科要求，正式填报前必须接入官方选科数据")

    if candidate.max_tuition is not None and latest.tuition is not None:
        if latest.tuition > candidate.max_tuition:
            reasons.append(f"学费 {latest.tuition} 超过上限 {candidate.max_tuition}")

    if latest.city and latest.city in candidate.blocked_cities:
        reasons.append(f"城市 {latest.city} 在排除列表中")

    if not candidate.allow_private and not is_public_undergraduate(latest):
        reasons.append("用户未接受民办院校")

    if _is_sino_foreign_or_high_fee(latest) and not candidate.allow_sino_foreign:
        reasons.append("用户未接受中外合作/高收费项目")

    profile_tags = set(school_tags(latest))
    if candidate.require_double_first_class and "双一流" not in profile_tags:
        reasons.append("不符合筛选：只看双一流")
    if candidate.require_985 and "985" not in profile_tags:
        reasons.append("不符合筛选：只看985")
    if candidate.require_211 and "211" not in profile_tags:
        reasons.append("不符合筛选：只看211")
    if candidate.require_public_undergraduate and not is_public_undergraduate(latest):
        reasons.append("不符合筛选：只看公办本科")

    if candidate.interests:
        matched_interest = any(
            _interest_match_level_for_record(
                keyword,
                latest,
                allow_related=False,
                allow_school_related=True,
            ) == "direct"
            for keyword in candidate.interests
        )
        if not matched_interest:
            reasons.append("专业与用户提供的专业选择无关")

    haystack = " ".join([latest.school_name, latest.major_name, latest.school_type, *latest.tags])
    for keyword in candidate.avoid_keywords:
        if keyword and keyword in haystack:
            reasons.append(f"包含排斥关键词：{keyword}")

    if reasons:
        return Rejection(latest.option_key, latest.option_name, tuple(reasons))
    return None


SUBJECT_ORDER = ("物理", "化学", "生物", "思想政治", "历史", "地理")


def _normalize_subject(subject: str) -> str:
    aliases = {
        "政治": "思想政治",
        "思想政治": "思想政治",
    }
    return aliases.get(subject, subject)


def _required_subjects(subjects: tuple[str, ...]) -> tuple[str, ...]:
    required: list[str] = []
    joined = " ".join(str(subject or "") for subject in subjects)
    for subject in SUBJECT_ORDER:
        aliases = (subject,)
        if subject == "思想政治":
            aliases = ("思想政治", "政治")
        if any(alias in joined or alias in subjects for alias in aliases):
            if subject not in required:
                required.append(subject)
    if required:
        return tuple(required)
    return tuple(_normalize_subject(subject) for subject in subjects if subject)


def _is_sino_foreign_or_high_fee(record: AdmissionRecord) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            record.school_name,
            record.major_name,
            record.school_type,
            *record.tags,
        )
    )
    return any(marker in text for marker in ("中外合作", "合作办学", "高收费"))


def _professional_text(record: AdmissionRecord) -> str:
    return record.major_name


def _interest_matches_professional(keyword: str, professional_text: str) -> bool:
    return _interest_match_level(keyword, professional_text) == "direct"


def _interest_match_level_for_record(
    keyword: str,
    record: AdmissionRecord,
    *,
    allow_related: bool = True,
    allow_school_related: bool = True,
) -> str | None:
    school_mapped = _interest_match_level_from_school_major_map(
        keyword,
        record,
        allow_related=allow_related or allow_school_related,
    )
    if school_mapped is not None:
        if school_mapped == "related" and not allow_related and allow_school_related:
            return "direct"
        return school_mapped
    mapped = _interest_match_level_from_major_map(keyword, record, allow_related=allow_related)
    if mapped is not None:
        return mapped
    match_level = _interest_match_level(keyword, _professional_text(record))
    if match_level == "direct":
        return "direct"
    if _has_known_major_map_entry(record):
        return "direct" if keyword == "师范" and "师范" in record.tags else None

    if allow_related and match_level == "related":
        return match_level
    if keyword == "师范" and "师范" in record.tags:
        return "direct"
    return None


def _interest_match_level_from_school_major_map(
    keyword: str,
    record: AdmissionRecord,
    *,
    allow_related: bool = True,
) -> str | None:
    entry = _interest_school_major_map().get(_school_major_map_key(record.school_name, record.major_name))
    if not entry:
        return None
    if keyword in set(entry.get("direct", ())):
        return "direct"
    if keyword in set(entry.get("related", ())) and allow_related:
        return "related"
    return None


def _interest_match_level_from_major_map(
    keyword: str,
    record: AdmissionRecord,
    *,
    allow_related: bool = True,
) -> str | None:
    entry = _interest_major_map().get(record.major_name)
    if not entry:
        return None
    if keyword in set(entry.get("direct", ())):
        return "direct"
    if keyword in set(entry.get("related", ())) and allow_related:
        return "related"
    return None


def _has_known_major_map_entry(record: AdmissionRecord) -> bool:
    return record.major_name in _interest_major_map()


def _school_major_map_key(school_name: str, major_name: str) -> str:
    return f"{school_name.strip()}|{major_name.strip()}"


def _interest_school_major_map() -> dict[str, dict[str, list[str]]]:
    if not hasattr(_interest_school_major_map, "_cache"):
        setattr(_interest_school_major_map, "_cache", _load_interest_school_major_map())
    return getattr(_interest_school_major_map, "_cache")


def _load_interest_school_major_map() -> dict[str, dict[str, list[str]]]:
    if os.environ.get("GAOKAO_DISABLE_INTEREST_MAJOR_MAP") == "1":
        return {}
    if not INTEREST_SCHOOL_MAJOR_MAP_PATH.exists():
        return {}
    result: dict[str, dict[str, list[str]]] = {}
    try:
        with INTEREST_SCHOOL_MAJOR_MAP_PATH.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                if str(row.get("action") or "map").strip() != "map":
                    continue
                school = str(row.get("school_name") or "").strip()
                major = str(row.get("major_name") or "").strip()
                if not school or not major:
                    continue
                result[_school_major_map_key(school, major)] = {
                    "direct": _split_interest_labels(row.get("direct_interests")),
                    "related": _split_interest_labels(row.get("related_interests")),
                }
    except OSError:
        return {}
    return result


def _split_interest_labels(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    for separator in ("、", "|", "，", ",", ";", "；", "/"):
        text = text.replace(separator, "|")
    labels = set(INTEREST_LABELS)
    result: list[str] = []
    for part in (item.strip() for item in text.split("|")):
        if part and part in labels and part not in result:
            result.append(part)
    return result


def _interest_major_map() -> dict[str, dict[str, list[str]]]:
    if not hasattr(_interest_major_map, "_cache"):
        setattr(_interest_major_map, "_cache", _load_interest_major_map())
    return getattr(_interest_major_map, "_cache")


def _load_interest_major_map() -> dict[str, dict[str, list[str]]]:
    if os.environ.get("GAOKAO_DISABLE_INTEREST_MAJOR_MAP") == "1":
        return {}
    if not INTEREST_MAJOR_MAP_PATH.exists():
        return {}
    try:
        payload = json.loads(INTEREST_MAJOR_MAP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if payload.get("version") != INTEREST_MAJOR_MAP_VERSION:
        return {}
    majors = payload.get("majors")
    if not isinstance(majors, dict):
        return {}
    return {
        str(major): {
            "direct": list(value.get("direct", ())),
            "related": list(value.get("related", ())),
        }
        for major, value in majors.items()
        if isinstance(value, dict)
    }


def _interest_match_level(keyword: str, professional_text: str) -> str | None:
    if not keyword:
        return None
    if _interest_context_excluded(keyword, professional_text):
        return None
    if _direct_interest_match(keyword, professional_text):
        return "direct"
    standard_match = _standard_major_match_level(keyword, professional_text)
    if standard_match is not None:
        return standard_match
    narrow_match = _narrow_interest_match_level(keyword, professional_text)
    if narrow_match is not None:
        return narrow_match
    if keyword in NARROW_INTEREST_ALIASES:
        return None

    if _interest_is_professionally_related(keyword, professional_text):
        return "related"
    return None


def _interest_context_excluded(keyword: str, professional_text: str) -> bool:
    tech_keywords = {
        "计算机", "软件", "人工智能", "数据科学", "网络空间安全", "信息安全",
        "电子", "电子信息", "通信工程", "集成电路", "微电子", "物联网",
        "智能科学", "自动化", "机器人工程", "仪器测控",
    }
    if "电子商务" in professional_text and keyword in tech_keywords:
        return True

    cyber_keywords = {"网络空间安全", "信息安全"}
    math_major_markers = ("数学", "统计学", "统计")
    if keyword in cyber_keywords and any(marker in professional_text for marker in math_major_markers):
        if not any(marker in professional_text for marker in ("网络空间安全", "信息安全", "密码", "保密技术")):
            return True

    return False


DIRECT_INTEREST_ALIASES = {
    "计算机": {
        "计算机", "计算机科学与技术", "软件工程", "网络工程", "信息安全", "物联网工程",
        "数字媒体技术", "智能科学与技术", "空间信息与数字技术", "电子与计算机工程",
        "数据科学与大数据技术", "网络空间安全", "新媒体技术", "保密技术",
        "服务科学与工程", "虚拟现实技术", "区块链工程", "密码科学与技术", "工业软件",
        "云计算技术",
    },
    "数据科学": {
        "数据科学", "大数据", "数据计算及应用", "数字经济", "经济统计", "统计学",
    },
    "网络空间安全": {
        "网络空间安全", "网络安全", "信息安全", "密码科学与技术", "保密技术", "信息对抗技术",
    },
    "信息安全": {
        "信息安全", "网络安全", "网络空间安全", "密码科学与技术", "保密技术", "信息对抗技术", "保密管理",
    },
    "电子": {
        "电子信息", "电子科学", "电子工程", "微电子", "光电信息", "电子封装",
        "电子与计算机", "应用电子", "电波传播",
    },
    "电子信息": {
        "电子信息", "电子科学", "光源与照明", "导航工程", "水声工程", "广播电视工程",
    },
    "通信工程": {
        "通信工程", "信息工程", "电波传播", "水声工程", "广播电视工程",
    },
    "自动化": {
        "自动化", "机器人工程", "智能装备与系统", "智能装备", "智能制造", "农业智能装备工程",
    },
    "机械": {
        "机械", "智能制造", "过程装备与控制工程", "汽车服务工程", "农业智能装备工程",
        "增材制造工程", "应急装备技术与工程",
    },
    "车辆工程": {"车辆工程", "汽车服务工程", "新能源汽车工程"},
    "电气": {"电气", "光源与照明", "智能电网", "储能科学与工程"},
    "能源": {"能源", "核工程与核技术", "储能科学与工程", "能源动力"},
    "材料": {
        "材料", "焊接技术与工程", "包装工程", "印刷工程", "轻化工程",
        "丝绸设计与工程", "木材科学与工程", "林业工程",
    },
    "土木": {
        "土木", "道路桥梁与渡河工程", "给排水科学与工程", "城市地下空间工程",
        "智能建造", "工程造价", "建筑工程", "智慧建筑与建造", "地下水科学与工程",
        "工程力学", "理论与应用力学",
    },
    "交通": {"交通", "道路桥梁与渡河工程", "物流工程", "航海技术", "轮机工程"},
    "水利": {"水利", "水文与水资源工程", "港口航道与海岸工程", "给排水科学与工程"},
    "测绘": {"测绘", "导航工程", "地理空间信息工程", "遥感科学与技术"},
    "地理科学": {"地理科学", "自然地理与资源环境", "土地科学与技术", "地理空间信息工程"},
    "大气科学": {"大气科学", "应用气象学", "气象技术与工程"},
    "海洋科学": {"海洋科学", "海洋技术", "海洋资源与环境"},
    "地质学": {"地质学", "古生物学", "行星科学", "资源勘查工程"},
    "环境工程": {
        "环境工程", "环境生态工程", "环保设备工程", "农业资源与环境",
        "水土保持与荒漠化防治", "资源环境科学", "自然保护与环境生态",
    },
    "安全工程": {"安全工程", "安全科学与工程", "应急技术与管理", "应急管理", "防灾减灾科学与工程", "职业卫生工程"},
    "兵器": {"兵器", "弹药工程与爆炸技术", "探测制导与控制技术", "信息对抗技术"},
    "数学": {"数学", "信息与计算科学", "数据计算及应用", "数理基础科学", "工程力学", "力学类"},
    "统计": {"统计", "数据计算及应用", "经济统计", "数字经济"},
    "物理": {"物理", "工程力学", "理论与应用力学", "核工程与核技术", "光源与照明", "力学类"},
    "应用物理": {"应用物理", "工程力学", "理论与应用力学", "光源与照明", "力学类"},
    "化学": {"化学", "化工与制药", "应用化工技术", "制药工程", "轻化工程", "化妆品科学与技术", "化妆品技术与工程", "农药化肥"},
    "应用化学": {"应用化学", "化工与制药", "应用化工技术", "制药工程", "轻化工程", "化妆品科学与技术", "化妆品技术与工程", "农药化肥"},
    "生物科学": {
        "生物科学", "生物技术", "生物工程", "生物制药", "合成生物学",
        "生物育种科学", "生物信息学", "仿生科学与工程", "古生物学",
    },
    "设计": {
        "设计学", "艺术设计", "视觉传达设计", "环境设计", "产品设计", "服装与服饰设计",
        "数字媒体艺术", "工艺美术", "工业设计",
    },
    "医学": {
        "临床医学", "口腔医学", "基础医学", "预防医学", "中医学", "中西医临床医学",
        "麻醉学", "医学影像", "医学检验", "眼视光医学", "精神医学", "儿科学",
        "放射医学", "智能医学", "生物医学工程", "医学技术", "医学实验技术",
        "智能影像工程", "健康服务与管理", "医养照护与管理",
    },
    "医学影像": {"医学影像", "智能影像工程"},
    "医学检验": {"医学检验", "医学实验技术", "卫生检验"},
    "护理学": {"护理学", "助产学", "医养照护与管理", "养老服务管理"},
    "康复治疗": {"康复治疗", "运动康复", "假肢矫形工程", "医养照护与管理"},
    "预防医学": {"预防医学", "职业卫生工程", "卫生检验与检疫"},
    "药学": {"药学", "制药工程", "生物制药", "药物制剂", "临床药学", "化妆品科学与技术", "药物分析"},
    "经济学": {"经济学", "数字经济", "国民经济管理", "贸易经济", "经济统计", "国际经济发展合作"},
    "国际经济与贸易": {"国际经济与贸易", "国际商务", "贸易经济", "跨境电子商务"},
    "金融": {"金融", "信用管理", "信用风险管理与法律防控", "保险学", "投资学", "精算学"},
    "税收学": {"税收学", "国际税收"},
    "会计学": {"会计学", "内部审计", "工程审计"},
    "审计学": {"审计学", "内部审计", "工程审计"},
    "工商管理": {
        "工商管理", "国际商务", "农林经济管理", "工业工程", "质量管理工程",
        "标准化工程", "企业数字化管理", "创业管理", "物业管理",
    },
    "公共管理": {
        "公共管理", "公共事业管理", "土地资源管理", "房地产开发与管理", "健康服务与管理",
        "劳动与社会保障", "养老服务管理", "乡村治理", "应急管理", "党务工作",
        "物业管理", "医疗产品管理", "国家公园建设与管理", "劳动关系",
    },
    "社会学": {"社会学", "民族学", "社会工作", "家政学"},
    "政治学": {
        "政治学", "国际政治", "外交学", "国际事务与国际关系", "中国共产党历史",
        "党务工作", "国际组织与全球治理",
    },
    "法学": {"法学", "国际法", "国际经贸规则", "信用风险管理与法律防控", "纪检监察", "劳动关系"},
    "公安学": {"公安学", "刑事科学技术", "反恐警务", "侦查学", "治安学"},
    "汉语言文学": {
        "汉语言文学", "中国语言文学", "中国语言与文化", "汉语国际教育", "中文国际教育",
        "中国少数民族语言文学", "古典文献学", "中国古典学",
    },
    "新闻传播": {
        "新闻传播", "全媒体新闻采编与制作", "广播电视编导", "广播电视学",
        "传播学", "数字出版", "公共关系学",
    },
    "戏剧影视": {"戏剧影视", "广播电视编导", "电影学", "戏剧学", "艺术管理"},
    "美术学": {"美术学", "艺术史论", "艺术管理"},
    "教育学": {"教育学", "教育技术学", "科学教育", "艺术教育", "劳动教育"},
    "农学": {
        "农学", "植物生产", "智慧农业", "农业资源与环境", "农村区域发展",
        "植物科学与技术", "智慧牧业科学与工程", "烟草", "茶学", "设施农业科学与工程",
        "农业工程类", "农药化肥",
    },
    "植物保护": {"植物保护", "动植物检疫", "植物生产", "农药化肥"},
    "园艺": {"园艺", "园林", "植物生产"},
    "林学": {"林学", "园林", "智慧林业", "木材科学与工程", "林业工程"},
    "水产": {"水产", "水族科学与技术", "海洋渔业科学与技术"},
    "动物科学": {"动物科学", "智慧牧业科学与工程", "动植物检疫", "动物生产", "蚕学", "马业科学"},
    "食品科学": {"食品科学", "烹饪与营养教育", "食品营养", "食品质量"},
    "食品质量": {"食品质量", "食品安全", "烹饪与营养教育"},
    "草业科学": {"草业科学", "草坪科学与工程"},
    "历史学": {"历史学", "世界史", "中国共产党历史", "中国古典学"},
    "仪器测控": {
        "测控技术与仪器", "仪器类", "精密仪器", "智能感知工程", "光电信息科学与工程",
        "智能光电", "智能感知", "传感器", "仪器仪表",
    },
    "航空飞行": {
        "飞行技术", "飞行器", "航空航天工程", "无人驾驶航空器系统工程",
        "智慧民航", "低空技术与工程", "飞行器适航技术", "空中交通管理",
    },
    "矿业资源": {
        "采矿工程", "矿物加工工程", "矿物资源工程", "资源勘查工程", "勘查技术与工程",
        "地质工程", "石油工程", "油气储运工程", "海洋油气工程", "煤层气", "矿业",
    },
    "食品酿造": {
        "酿酒工程", "葡萄与葡萄酒工程", "食品科学与工程", "食品质量与安全",
        "食品营养与健康", "食品安全与检测", "食品工程技术", "食品营养与检验教育",
        "食用菌科学与工程", "香料香精技术与工程", "粮食工程", "乳品工程",
    },
    "中医药细分": {
        "中医养生学", "中医康复学", "中医骨伤科学", "中兽医学", "中草药栽培与鉴定",
        "中药制药", "中药资源与开发", "中药学", "针灸推拿学", "中医学",
        "中西医临床医学",
    },
    "小语种": {
        "俄语", "日语", "德语", "法语", "西班牙语", "阿拉伯语", "朝鲜语", "葡萄牙语",
        "意大利语", "泰语", "越南语", "缅甸语", "老挝语", "马来语", "印地语",
        "印度尼西亚语", "柬埔寨语", "菲律宾语", "乌尔都语", "波斯语", "土耳其语", "乌克兰语", "保加利亚语", "希腊语",
        "捷克语", "波兰语", "塞尔维亚语", "匈牙利语", "罗马尼亚语", "瑞典语",
        "芬兰语", "挪威语", "丹麦语", "荷兰语", "克罗地亚语", "斯瓦希里语",
        "豪萨语", "祖鲁语", "僧伽罗语", "尼泊尔语", "梵语巴利语", "希伯来语",
        "亚美尼亚语", "爱沙尼亚语", "拉脱维亚语", "立陶宛语", "冰岛语",
        "波斯尼亚语", "阿尔巴尼亚语", "蒙古语", "哈萨克语",
    },
    "体育运动": {
        "体育教育", "运动训练", "社会体育指导与管理", "武术与民族传统体育",
        "运动人体科学", "运动康复", "休闲体育", "体能训练", "冰雪运动",
        "电子竞技运动与管理", "体育旅游", "体育经济与管理", "智能体育工程",
    },
    "文化遗产": {
        "文物与博物馆学", "文物保护技术", "文化遗产", "非物质文化遗产保护",
        "考古学", "历史建筑保护工程",
    },
    "图书情报": {"图书情报", "信息资源管理"},
    "信息管理与信息系统": {"信息管理与信息系统", "信息资源管理", "管理科学"},
    "会展传播": {
        "会展经济与管理", "会展", "传播学", "新闻学", "广播电视学",
        "国际新闻与传播", "网络与新媒体", "广告学", "编辑出版学",
    },
    "采购零售": {
        "采购管理", "零售业管理", "供应链管理", "物流管理", "电子商务", "市场营销",
    },
}


def _direct_interest_match(keyword: str, professional_text: str) -> bool:
    if keyword == "英语":
        return (
            professional_text.startswith("英语")
            or "商务英语" in professional_text
            or "应用英语" in professional_text
            or "翻译" in professional_text
            or "外国语言文学" in professional_text
        )
    aliases = DIRECT_INTEREST_ALIASES.get(keyword)
    if aliases is not None:
        if any(_direct_alias_matches(alias, professional_text) for alias in aliases):
            return True
        direction_text = _explicit_direction_text(professional_text)
        return bool(direction_text) and any(alias in direction_text for alias in aliases)
    return keyword in professional_text


def _standard_major_match_level(keyword: str, professional_text: str) -> str | None:
    """Match a national standard major name to Shandong admission category names."""
    entry = _standard_major_catalog().get(keyword)
    if not entry:
        return None
    if keyword in professional_text:
        return "direct"
    category = str(entry.get("category") or "").strip()
    if category and category in professional_text:
        return "direct"
    return None


def _standard_major_catalog() -> dict[str, dict[str, str]]:
    if not hasattr(_standard_major_catalog, "_cache"):
        setattr(_standard_major_catalog, "_cache", _load_standard_major_catalog())
    return getattr(_standard_major_catalog, "_cache")


def _load_standard_major_catalog() -> dict[str, dict[str, str]]:
    if not UNDERGRADUATE_MAJOR_CATALOG_PATH.exists():
        return {}
    try:
        payload = json.loads(UNDERGRADUATE_MAJOR_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    majors = payload.get("majors")
    if not isinstance(majors, list):
        return {}
    result: dict[str, dict[str, str]] = {}
    for item in majors:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        result[name] = {
            "code": str(item.get("code") or "").strip(),
            "category": str(item.get("category") or "").strip(),
            "discipline": str(item.get("discipline") or "").strip(),
        }
    return result


def _direct_alias_matches(alias: str, professional_text: str) -> bool:
    return professional_text == alias or professional_text.startswith(alias)


def _explicit_trial_class_direction(professional_text: str) -> str:
    if not any(marker in professional_text for marker in ("试验班", "实验班", "拔尖")):
        return ""
    return _parenthetical_direction_text(professional_text)


def _explicit_direction_text(professional_text: str) -> str:
    direction = _explicit_trial_class_direction(professional_text)
    if direction:
        return direction
    if "类" not in professional_text:
        return ""
    return _parenthetical_direction_text(professional_text)


def _parenthetical_direction_text(professional_text: str) -> str:
    for left, right in (("(", ")"), ("（", "）")):
        if left in professional_text and right in professional_text:
            return professional_text.split(left, 1)[1].split(right, 1)[0]
    return ""


NARROW_INTEREST_ALIASES = {
    "网络空间安全": {
        "网络空间安全", "信息安全", "网络工程", "密码科学", "密码科学与技术",
        "保密技术", "计算机", "软件", "数据科学", "人工智能", "智能科学",
        "电子信息", "通信工程", "信息工程", "物联网",
    },
    "信息安全": {
        "信息安全", "网络空间安全", "网络工程", "密码科学", "密码科学与技术",
        "保密技术", "计算机", "软件", "数据科学", "人工智能", "智能科学",
        "电子信息", "通信工程", "信息工程", "物联网",
    },
}


def _narrow_interest_match_level(keyword: str, professional_text: str) -> str | None:
    aliases = NARROW_INTEREST_ALIASES.get(keyword)
    if not aliases:
        return None
    if any(alias in professional_text for alias in aliases):
        return "related"
    return None


RELATED_INTEREST_ALIASES = {
    "计算机": {
        "软件", "人工智能", "数据科学", "大数据", "信息安全", "网络空间安全",
        "智能科学", "物联网", "区块链", "密码科学", "数字媒体技术", "统计",
        "信息类", "信息科学", "信息技术", "信息智能",
    },
    "软件": {"计算机", "人工智能", "数据科学", "大数据", "信息安全", "网络空间安全"},
    "人工智能": {"计算机", "软件", "数据科学", "智能科学", "机器人工程", "自动化", "统计"},
    "数据科学": {"计算机", "软件", "人工智能", "统计", "数学", "大数据", "数据管理"},
    "电子": {"电子信息", "通信工程", "集成电路", "微电子", "光电信息", "测控技术", "自动化"},
    "电子信息": {
        "电子", "通信工程", "集成电路", "微电子", "光电信息", "测控技术",
        "自动化", "信息类", "信息科学", "信息技术", "信息智能",
    },
    "通信工程": {"电子信息", "电子", "信息工程", "网络工程", "物联网", "集成电路", "信息类"},
    "集成电路": {"微电子", "电子", "电子信息", "半导体"},
    "微电子": {"集成电路", "电子", "电子信息", "半导体"},
    "物联网": {"计算机", "软件", "电子信息", "通信工程", "自动化"},
    "智能科学": {"人工智能", "计算机", "软件", "数据科学", "机器人工程", "自动化"},
    "自动化": {"机器人工程", "智能制造", "测控技术", "电气", "电子信息", "人工智能"},
    "机器人工程": {"自动化", "人工智能", "机械", "智能制造", "电气"},
    "仪器测控": {"测控技术", "精密仪器", "智能感知", "光电信息", "自动化", "电子信息"},
    "机械": {"智能制造", "机器人工程", "车辆工程", "机械设计"},
    "电气": {"自动化", "能源", "新能源", "储能", "智能电网"},
    "车辆工程": {"机械", "交通", "能源", "新能源"},
    "航空航天": {"机械", "自动化", "材料", "飞行器"},
    "航空飞行": {"航空航天", "飞行器", "交通运输", "空中交通", "无人机", "低空"},
    "船舶": {"机械", "海洋工程", "交通"},
    "兵器": {"机械", "自动化", "材料"},
    "土木": {"建筑环境", "交通", "水利", "工程管理"},
    "建筑环境": {"土木", "能源", "环境工程"},
    "交通": {"车辆工程", "土木", "物流管理"},
    "能源": {"电气", "新能源", "储能", "动力工程"},
    "新能源": {"能源", "电气", "储能", "材料"},
    "材料": {"化学", "应用化学", "新能源", "冶金"},
    "冶金": {"材料", "能源"},
    "测绘": {"地理科学", "地理信息", "遥感"},
    "矿业资源": {"地质学", "资源勘查", "采矿", "矿物", "石油工程", "油气储运", "安全工程"},
    "水利": {"土木", "环境工程"},
    "环境工程": {"环境科学", "生态学", "水利"},
    "安全工程": {"应急技术", "消防工程", "环境工程"},
    "数学": {"统计", "数据科学", "人工智能", "计算机"},
    "统计": {"数学", "数据科学", "大数据", "人工智能", "经济统计"},
    "物理": {"应用物理", "光电信息", "电子", "材料", "能源"},
    "应用物理": {"物理", "光电信息", "电子", "材料"},
    "化学": {"应用化学", "材料", "药学", "食品科学"},
    "应用化学": {"化学", "材料", "药学", "食品科学"},
    "生物科学": {"生物技术", "生态学", "农学", "基础医学", "生物医学工程"},
    "地理科学": {"测绘", "地理信息", "遥感", "城乡规划"},
    "大气科学": {"海洋科学", "环境科学", "地理科学"},
    "海洋科学": {"大气科学", "水产", "海洋工程"},
    "地质学": {"测绘", "资源勘查", "地理科学"},
    "生态学": {"环境工程", "生物科学", "农学"},
    "心理学": {"应用心理学", "精神医学", "教育学", "社会工作"},
    "医学": {
        "临床医学", "口腔医学", "基础医学", "麻醉学", "医学影像", "眼视光医学",
        "精神医学", "儿科学", "预防医学", "中医学", "药学", "医学检验", "护理学",
        "康复治疗", "生物医学工程", "心理学",
    },
    "临床医学": {"麻醉学", "医学影像", "眼视光医学", "精神医学", "儿科学", "预防医学"},
    "口腔医学": {"口腔医学技术"},
    "基础医学": {"生物医学", "生物科学", "临床医学"},
    "预防医学": {"公共卫生", "卫生检验", "食品卫生"},
    "中医学": {"针灸推拿", "中药学", "中西医临床医学"},
    "中医药细分": {"中医学", "中药学", "针灸推拿", "中医康复", "中医养生", "中医骨伤"},
    "药学": {"临床药学", "药物制剂", "中药学", "化学", "应用化学"},
    "医学影像": {"医学影像学", "放射医学", "医学影像技术"},
    "医学检验": {"医学检验技术", "卫生检验"},
    "护理学": {"助产学", "康复治疗"},
    "康复治疗": {"护理学", "运动康复"},
    "生物医学工程": {"生物科学", "医疗器械", "智能医学工程", "医学信息工程"},
    "金融": {"经济学", "财政学", "税收学", "会计学", "财务管理", "审计学", "精算", "保险", "投资"},
    "经济学": {"金融", "财政学", "税收学", "国际经济与贸易", "经济统计"},
    "财政学": {"税收学", "经济学", "金融", "会计学"},
    "税收学": {"财政学", "经济学", "会计学"},
    "会计学": {"财务管理", "审计学", "财政学", "税收学"},
    "财务管理": {"会计学", "审计学", "金融"},
    "审计学": {"会计学", "财务管理"},
    "工商管理": {"市场营销", "人力资源", "物流管理", "电子商务"},
    "市场营销": {"工商管理", "电子商务", "广告学"},
    "人力资源": {"工商管理", "心理学", "公共管理"},
    "物流管理": {"工商管理", "交通", "电子商务", "供应链"},
    "会展传播": {"新闻传播", "传播学", "广告学", "网络与新媒体", "文化产业管理", "市场营销"},
    "采购零售": {"供应链", "物流管理", "电子商务", "市场营销", "工商管理"},
    "信息管理与信息系统": {"数据管理", "电子商务", "计算机", "管理科学"},
    "数据管理": {"数据科学", "信息管理与信息系统", "统计", "计算机"},
    "电子商务": {"工商管理", "市场营销", "物流管理", "信息管理与信息系统"},
    "国际经济与贸易": {"经济学", "金融", "外国语言文学", "英语"},
    "法学": {"知识产权", "纪检监察", "司法", "公安学", "政治学"},
    "知识产权": {"法学"},
    "政治学": {"法学", "思想政治教育", "行政管理", "公共管理"},
    "思想政治教育": {"政治学", "马克思主义理论"},
    "社会学": {"社会工作", "公共管理", "行政管理"},
    "社会工作": {"社会学", "公共管理", "心理学"},
    "公共管理": {"行政管理", "社会学", "社会工作", "政治学"},
    "行政管理": {"公共管理", "政治学", "社会学"},
    "公安学": {"法学", "国家安全", "侦查学"},
    "马克思主义理论": {"思想政治教育", "政治学"},
    "师范": {"教育学", "学前教育", "小学教育", "特殊教育"},
    "教育学": {"学前教育", "小学教育", "心理学", "特殊教育"},
    "学前教育": {"教育学", "小学教育", "心理学"},
    "小学教育": {"教育学", "学前教育", "心理学"},
    "汉语言文学": {"汉语言", "新闻传播", "编辑出版"},
    "外国语言文学": {"英语", "翻译", "国际经济与贸易"},
    "英语": {"外国语言文学", "翻译", "国际经济与贸易"},
    "小语种": {"外国语言文学", "翻译", "国际经济与贸易"},
    "新闻传播": {"广告学", "网络与新媒体", "编辑出版", "汉语言文学"},
    "广告学": {"新闻传播", "网络与新媒体", "市场营销"},
    "网络与新媒体": {"新闻传播", "广告学", "数字媒体"},
    "编辑出版": {"新闻传播", "汉语言文学", "图书情报"},
    "播音主持": {"新闻传播", "戏剧影视"},
    "设计": {"工业设计", "数字媒体", "动画", "美术学", "广告学", "建筑学", "城乡规划", "风景园林"},
    "工业设计": {"产品设计", "智能交互设计", "家具设计"},
    "数字媒体": {"动画", "网络与新媒体", "计算机"},
    "动画": {"数字媒体", "戏剧影视"},
    "美术学": {"动画", "艺术设计", "视觉传达", "环境设计", "产品设计", "数字媒体艺术"},
    "音乐学": {"艺术教育"},
    "戏剧影视": {"动画", "数字媒体", "播音主持"},
    "体育运动": {"体育教育", "运动康复", "休闲体育", "康复治疗", "体育经济"},
    "建筑学": {"城乡规划", "风景园林", "土木"},
    "城乡规划": {"建筑学", "风景园林", "地理科学"},
    "风景园林": {"建筑学", "城乡规划", "林学"},
    "服装设计": {"服装与服饰设计", "纺织"},
    "农学": {"植物保护", "园艺", "生态学", "生物科学"},
    "植物保护": {"农学", "园艺", "生态学"},
    "园艺": {"农学", "植物保护", "林学"},
    "动物医学": {"动物科学", "农学"},
    "动物科学": {"动物医学", "农学"},
    "林学": {"园艺", "风景园林", "生态学"},
    "水产": {"海洋科学", "动物科学", "食品科学"},
    "食品科学": {"食品质量", "化学", "生物科学", "农学"},
    "食品质量": {"食品科学", "化学", "生物科学"},
    "食品酿造": {"食品科学", "食品质量", "生物科学", "化学", "酿酒"},
    "草业科学": {"农学", "生态学"},
    "历史学": {"考古学", "文化产业管理"},
    "考古学": {"历史学", "文物保护"},
    "文化遗产": {"历史学", "考古学", "文物保护", "文化产业管理", "旅游管理"},
    "哲学": {"政治学", "马克思主义理论"},
    "档案学": {"图书情报", "信息管理与信息系统"},
    "图书情报": {"档案学", "信息管理与信息系统", "编辑出版"},
    "文化产业管理": {"旅游管理", "历史学", "新闻传播"},
    "旅游管理": {"酒店管理", "文化产业管理"},
    "酒店管理": {"旅游管理", "工商管理"},
}


def _interest_is_professionally_related(keyword: str, professional_text: str) -> bool:
    aliases = RELATED_INTEREST_ALIASES.get(keyword, set())
    return any(alias in professional_text for alias in aliases)


def weighted_reference_rank(records: list[AdmissionRecord]) -> float | None:
    weighted_sum = 0.0
    used_weight = 0.0
    for record in records:
        if record.min_rank is None:
            continue
        weight = YEAR_WEIGHTS.get(record.year, 0.10)
        weighted_sum += record.min_rank * weight
        used_weight += weight
    if used_weight == 0:
        return None
    return weighted_sum / used_weight


RiskThresholds = tuple[float, float, float, float, float]


def classify_risk(
    candidate_rank: int,
    reference_rank: float | None,
    risk_thresholds: RiskThresholds | None = None,
) -> tuple[str, float, float | None]:
    if reference_rank is None:
        return "证据不足", 0.25, None

    margin = reference_rank - candidate_rank
    hard, soft, steady_lean, steady, safe = risk_thresholds or _risk_thresholds(candidate_rank)
    if margin < -hard:
        return "高冲", 0.12, margin
    if margin < -soft:
        return "冲", 0.35, margin
    if margin <= steady_lean:
        return "稳中偏冲", 0.58, margin
    if margin <= steady:
        return "稳", 0.76, margin
    if margin <= safe:
        return "保", 0.88, margin
    return "强保", 0.95, margin


SUCCESS_PROBABILITY_BOUNDS = {
    "高冲": (0.05, 0.18),
    "冲": (0.18, 0.38),
    "稳中偏冲": (0.38, 0.60),
    "稳": (0.60, 0.78),
    "保": (0.78, 0.92),
    "强保": (0.92, 0.98),
    "证据不足": (0.08, 0.20),
}


def success_probability(
    candidate_rank: int,
    reference_rank: float | None,
    risk_band: str,
    fit: float,
    stability: float,
    risk_thresholds: RiskThresholds | None = None,
) -> float:
    low, high = SUCCESS_PROBABILITY_BOUNDS.get(risk_band, (0.08, 0.20))
    if reference_rank is None:
        return _clamp_probability((low + high) / 2)

    margin = reference_rank - candidate_rank
    hard, soft, steady_lean, steady, safe = risk_thresholds or _risk_thresholds(candidate_rank)
    if risk_band == "高冲":
        distance_ratio = abs(min(margin, -hard)) / max(hard, 1)
        position = 1 - min(1, max(0, (distance_ratio - 1) / 2.5))
    elif risk_band == "冲":
        position = (margin + hard) / max(hard - soft, 1)
    elif risk_band == "稳中偏冲":
        position = (margin + soft) / max(steady_lean + soft, 1)
    elif risk_band == "稳":
        position = (margin - steady_lean) / max(steady - steady_lean, 1)
    elif risk_band == "保":
        position = (margin - steady) / max(safe - steady, 1)
    elif risk_band == "强保":
        position = min(1, (margin - safe) / max(safe, 1))
    else:
        position = 0.5

    position = min(1, max(0, position))
    base = low + (high - low) * position
    adjustment = (fit - 0.5) * 0.04 + (stability - 0.7) * 0.03
    return _clamp_probability(min(high, max(low, base + adjustment)))


def _clamp_probability(value: float) -> float:
    return max(0.01, min(0.99, value))


def _risk_thresholds(candidate_rank: int) -> tuple[float, float, float, float, float]:
    if candidate_rank <= 500:
        return 200, 50, 100, 300, 800
    return (
        max(1000, candidate_rank * 0.12),
        max(300, candidate_rank * 0.03),
        max(500, candidate_rank * 0.08),
        max(1500, candidate_rank * 0.25),
        max(3500, candidate_rank * 0.50),
    )


def trend_label(records: list[AdmissionRecord]) -> str:
    ranked = sorted((record for record in records if record.min_rank is not None), key=lambda item: item.year)
    if len(ranked) < 2:
        return "样本不足"

    ranks = [record.min_rank for record in ranked if record.min_rank is not None]
    if all(later < earlier for earlier, later in zip(ranks, ranks[1:])):
        return "连续变难"
    if all(later > earlier for earlier, later in zip(ranks, ranks[1:])):
        return "连续变易"
    return "波动"


def stability_score(records: list[AdmissionRecord]) -> float:
    ranks = [record.min_rank for record in records if record.min_rank is not None]
    if len(ranks) < 2:
        return 0.45
    avg = mean(ranks)
    if avg <= 0:
        return 0.45
    spread = max(ranks) - min(ranks)
    ratio = spread / avg
    return max(0.20, min(0.95, 1.0 - ratio))


def fit_score(records: list[AdmissionRecord], candidate: CandidateProfile) -> tuple[float, list[str]]:
    latest = max(records, key=lambda item: item.year)
    score = 0.45
    reasons: list[str] = []

    for keyword in candidate.interests:
        match_level = _interest_match_level_for_record(keyword, latest)
        if match_level == "direct":
            score += 0.12
            reasons.append(f"匹配专业：{keyword}")
        elif match_level == "related":
            score += 0.04
            reasons.append(f"相关专业族：{keyword}")

    if candidate.preferred_cities and latest.city in candidate.preferred_cities:
        score += 0.10
        reasons.append(f"匹配偏好城市：{latest.city}")

    profile_tags = set(school_tags(latest))
    if latest.school_level in {"985", "211", "双一流", "省重点"}:
        score += 0.08
        reasons.append(f"院校层次：{latest.school_level}")
    elif "985" in profile_tags:
        score += 0.08
        reasons.append("院校层次：985")
    elif "211" in profile_tags:
        score += 0.08
        reasons.append("院校层次：211")
    elif "双一流" in profile_tags:
        score += 0.08
        reasons.append("院校层次：双一流")

    score = max(0.0, min(1.0, score))
    if not reasons:
        reasons.append("未命中专业选择关键词，主要依据位次安全性进入候选")
    return score, reasons


def evidence_points(records: list[AdmissionRecord]) -> tuple[EvidencePoint, ...]:
    return tuple(
        EvidencePoint(
            year=record.year,
            source_id=record.source_id,
            min_score=record.min_score,
            min_rank=record.min_rank,
            plan_count=record.plan_count,
        )
        for record in sorted(records, key=lambda item: item.year)
    )


def falsification_tests(records: list[AdmissionRecord], candidate: CandidateProfile) -> tuple[str, ...]:
    latest = max(records, key=lambda item: item.year)
    tests = [
        "若 2026 招生计划比近三年均值减少超过 20%，必须重新计算风险层。",
        "若 2026 选科要求、体检要求、语种或单科限制变化，必须重新做硬性过滤。",
        "若官方原始文件或清洗映射无法追溯，本推荐不得用于正式填报。",
    ]
    if candidate.max_tuition is not None:
        tests.append(f"若 2026 学费超过用户上限 {candidate.max_tuition}，该项必须剔除。")
    if not latest.subjects:
        tests.append("若 2026 官方选科要求无法确认，该项不得直接用于正式填报。")
    if _is_sino_foreign_or_high_fee(latest):
        tests.append("若用户最终不接受中外合作/高收费项目，该项必须剔除。")
    if not is_public_undergraduate(latest):
        tests.append("若用户最终不接受民办或独立学院，该项必须剔除。")
    return tuple(tests)
