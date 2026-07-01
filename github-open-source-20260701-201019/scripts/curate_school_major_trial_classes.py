from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from gaokao_decision.database import connect, fetch_admissions
from gaokao_decision.scoring import INTEREST_LABELS


LABELS = set(INTEREST_LABELS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create preliminary school-specific mappings for broad trial classes.")
    parser.add_argument("--db", default="data/local/gaokao.sqlite")
    parser.add_argument("--manual-review", default="data/processed/interest_major_manual_review.csv")
    parser.add_argument("--charter-registry", default="data/processed/charter_registry_2026.json")
    parser.add_argument("--review", default="data/processed/interest_school_major_manual_review.csv")
    parser.add_argument("--overrides", default="data/curated/interest_school_major_overrides.csv")
    args = parser.parse_args()

    manual_majors = _manual_major_names(Path(args.manual_review))
    charter_registry = _load_json(Path(args.charter_registry))
    with connect(args.db) as connection:
        records = fetch_admissions(connection)

    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for record in records:
        if record.major_name in manual_majors:
            grouped[(record.school_name, record.major_name)].append(record)

    review_rows = []
    override_rows = []
    for index, ((school, major), group) in enumerate(sorted(grouped.items()), 1):
        classification = classify_school_major(school, major)
        source_url = _source_url(school, charter_registry)
        years = "、".join(str(year) for year in sorted({record.year for record in group}))
        codes = "、".join(sorted({record.major_code for record in group}))
        row = {
            "index": index,
            "school_name": school,
            "major_name": major,
            "action": classification["action"],
            "decision": classification["decision"],
            "direct_interests": "、".join(classification["direct"]),
            "related_interests": "、".join(classification["related"]),
            "confidence": classification["confidence"],
            "basis": classification["basis"],
            "years": years,
            "major_codes": codes,
            "source_url": source_url,
        }
        review_rows.append(row)
        if row["action"] == "map":
            override_rows.append({
                "school_name": school,
                "major_name": major,
                "action": "map",
                "direct_interests": row["direct_interests"],
                "related_interests": row["related_interests"],
                "confidence": row["confidence"],
                "basis": row["basis"],
                "source_url": row["source_url"],
            })

    _write_csv(Path(args.review), review_rows, [
        "index",
        "school_name",
        "major_name",
        "action",
        "decision",
        "direct_interests",
        "related_interests",
        "confidence",
        "basis",
        "years",
        "major_codes",
        "source_url",
    ])
    _write_csv(Path(args.overrides), override_rows, [
        "school_name",
        "major_name",
        "action",
        "direct_interests",
        "related_interests",
        "confidence",
        "basis",
        "source_url",
    ])

    print({
        "review": args.review,
        "overrides": args.overrides,
        "school_major_count": len(review_rows),
        "override_count": len(override_rows),
        "manual_count": sum(1 for row in review_rows if row["action"] != "map"),
    })


def _manual_major_names(path: Path) -> set[str]:
    result = set()
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            if row.get("action") != "map" and row.get("major_name"):
                result.add(str(row["major_name"]).strip())
    return result


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def classify_school_major(school: str, major: str) -> dict[str, object]:
    if "本科预科班" in major:
        return _result(
            "review",
            "不按兴趣自动匹配",
            [],
            [],
            "manual",
            "边防军人子女预科班不对应固定本科专业方向，不能按兴趣归类。",
        )

    if "商学院" in major:
        return _result(
            "map",
            "院校级初步归类",
            [],
            ["工商管理", "金融", "经济学", "会计学", "市场营销"],
            "preliminary",
            "按院校学院名称和商科招生方向初步归入财经管理类；需继续核对具体专业分流。",
        )
    if "文学与社会科学院" in major:
        return _result(
            "map",
            "院校级初步归类",
            [],
            ["汉语言文学", "新闻传播", "社会学", "社会工作", "公共管理"],
            "preliminary",
            "按院校学院名称初步归入文学、传播和社会科学方向；需继续核对具体专业分流。",
        )
    if "理工学院" in major:
        return _result(
            "map",
            "院校级初步归类",
            [],
            ["计算机", "数据科学", "电子信息", "建筑学", "数学"],
            "preliminary",
            "按院校学院名称初步归入理工方向；需继续核对具体专业分流。",
        )

    specific = _specific_school_rule(school, major)
    if specific:
        return _result("map", "院校级初步归类", [], specific[0], "preliminary", specific[1])

    broad = _broad_major_rule(major)
    if broad:
        return _result("map", "院校级初步归类", [], broad[0], "preliminary", broad[1])

    return _result(
        "review",
        "保留人工核验",
        [],
        [],
        "manual",
        "该院校大类未能从名称稳定判断分流方向，继续保留人工核验。",
    )


def _specific_school_rule(school: str, major: str) -> tuple[list[str], str] | None:
    if school == "东南大学" and "吴健雄" in major:
        return (
            ["电子信息", "机械", "能源", "土木", "建筑学", "数学", "物理"],
            "东南大学吴健雄班为强化/拔尖培养大类，公开专业说明涵盖电子信息、机械动力、高等理工和建筑等方向，按多工科与数理基础初步归类。",
        )
    if school == "北京理工大学" and ("徐特立" in major or "卓越" in major or "拔尖" in major):
        return (
            ["航空航天", "兵器", "机械", "车辆工程", "光电信息", "电子信息", "自动化", "计算机", "材料", "化学"],
            "北京理工大学相关试验班属于学校优势工科拔尖培养，结合学校招生专业方向初步归入空天、兵器、机械车辆、信息和材料化工。",
        )
    if school.startswith("哈尔滨工业大学") and "工科试验班" in major:
        if "港大优学班" in major:
            return (
                ["人工智能", "自动化", "计算机", "数据科学"],
                "哈尔滨工业大学2026本科招生专业页列明港大优学班为人工智能或自动化专业任选，并由港大计算与数据科学学院相关师资参与，按智能、自动化、计算和数据方向初步归类。",
            )
        return (
            ["计算机", "电子信息", "通信工程", "自动化", "机器人工程", "机械", "航空航天", "材料", "能源", "土木"],
            "哈尔滨工业大学工科试验班按其优势工科和专业说明初步归入计算机、信息、自动化、机电、空天、材料能源和土木方向。",
        )
    if school == "同济大学" and "国豪精英" in major:
        return (
            ["土木", "建筑学", "交通", "车辆工程", "环境工程", "机械", "电子信息", "数学", "物理"],
            "同济大学国豪精英班为拔尖创新人才培养，结合学校优势工程和理科方向初步归入土建交通、环境、机械信息和数理。",
        )
    if school == "同济大学" and "卓越计划" in major:
        return (
            ["土木", "交通", "车辆工程", "机械", "电子信息", "环境工程", "材料"],
            "同济大学卓越计划班按卓越工程师培养方向初步归入土木交通、车辆机械、信息、环境和材料。",
        )
    if school == "浙江大学" and "工科试验班" in major:
        return (
            ["计算机", "电子信息", "自动化", "机械", "电气", "材料", "能源", "土木", "航空航天"],
            "浙江大学工科试验班按学校工科大类和专业说明初步归入信息、电气、机械、材料能源、土木和空天方向。",
        )
    if school == "南京大学" and "技术科学试验班" in major:
        return (
            ["计算机", "电子信息", "人工智能", "自动化", "材料", "能源", "物理"],
            "南京大学技术科学试验班按技术科学/工程技术方向初步归入信息、智能、材料能源和物理。",
        )
    if school == "南京大学" and "工科试验班" in major:
        return (
            ["计算机", "软件", "人工智能", "电子信息", "自动化", "材料"],
            "南京大学工科试验班按工程技术类专业方向初步归入计算机、软件、智能、电子和材料。",
        )
    if school == "上海交通大学" and "工科试验班" in major:
        return (
            ["机械", "电子信息", "自动化", "计算机", "材料", "能源", "航空航天", "船舶"],
            "上海交通大学工科试验班按其工科平台和专业说明初步归入机械、电子信息、计算机、材料能源、空天和船海方向。",
        )
    if school == "上海交通大学" and ("理科试验班" in major or "自然科学试验班" in major):
        return (
            ["数学", "物理", "化学", "生物科学", "统计"],
            "上海交通大学理科/自然科学试验班按理科拔尖方向初步归入数学、物理、化学、生物和统计。",
        )
    if school == "北京航空航天大学":
        if "中法工程师" in major or "国际卓越工程师" in major or "中法未来科技" in major or "未来工程师" in major:
            return (
                ["航空航天", "航空飞行", "机械", "电子信息", "自动化", "计算机", "材料"],
                "北京航空航天大学相关中法/卓越工程师试验班按空天和工程师培养方向初步归入空天、机械、信息、自动化、计算机和材料。",
            )
        if "社会科学" in major:
            return (
                ["法学", "社会学", "公共管理", "经济学", "工商管理"],
                "北京航空航天大学社会科学试验班按社科管理方向初步归类。",
            )
    if school == "北京大学":
        if "理科" in major:
            return (
                ["数学", "物理", "化学", "生物科学", "地理科学", "心理学"],
                "北京大学理科基础类按基础理科招生方向初步归入数学、物理、化学、生命、地理和心理。",
            )
        if "文科" in major:
            return (
                ["汉语言文学", "历史学", "哲学", "外国语言文学", "法学", "社会学"],
                "北京大学文科基础类按基础文科招生方向初步归入文学、历史、哲学、外语、法学和社会学。",
            )
    if school == "清华大学":
        if "理科" in major:
            return (
                ["数学", "物理", "化学", "生物科学", "电子信息", "计算机"],
                "清华大学理科各专业按基础理科和理工交叉方向初步归类。",
            )
        if "文科" in major:
            return (
                ["汉语言文学", "历史学", "哲学", "法学", "社会学", "新闻传播"],
                "清华大学文科大类按文史哲、法学、社会科学和传播方向初步归类。",
            )
    return None


def _broad_major_rule(major: str) -> tuple[list[str], str] | None:
    if "人文科学试验班" in major:
        return (
            ["汉语言文学", "历史学", "哲学", "外国语言文学", "新闻传播"],
            "人文科学试验班按人文学科大类初步归入文学、历史、哲学、外语和传播方向。",
        )
    if "文科试验班" in major:
        return (
            ["汉语言文学", "历史学", "哲学", "法学", "社会学", "经济学", "工商管理"],
            "文科试验班按文科基础和经管法社交叉方向初步归类。",
        )
    if "社会科学试验班" in major:
        return (
            ["法学", "社会学", "政治学", "公共管理", "经济学", "工商管理"],
            "社会科学试验班按法学、社会学、政治公共管理和经管方向初步归类。",
        )
    if "自然科学试验班" in major:
        return (
            ["数学", "物理", "化学", "生物科学", "生态学"],
            "自然科学试验班按基础自然科学方向初步归类。",
        )
    if "理科试验班" in major:
        if "生态" in major or "环境" in major:
            return (
                ["生态学", "环境工程", "生物科学", "地理科学"],
                "理科试验班括号给出生态环境方向，按生态、环境、生命和地理科学初步归类。",
            )
        if "地球" in major or "资源" in major or "空间信息" in major:
            return (
                ["地质学", "地理科学", "测绘", "环境工程"],
                "理科试验班括号给出地球科学、资源环境或空间信息方向，按地学、地理信息和环境方向初步归类。",
            )
        return (
            ["数学", "物理", "化学", "生物科学", "统计", "地理科学"],
            "理科试验班按基础理科和拔尖培养方向初步归类。",
        )
    if "技术科学试验班" in major:
        return (
            ["计算机", "电子信息", "人工智能", "自动化", "材料", "物理"],
            "技术科学试验班按信息、智能、材料和物理交叉方向初步归类。",
        )
    if "工科试验班" in major:
        return (
            ["机械", "电气", "电子信息", "自动化", "计算机", "材料", "能源", "土木", "航空航天"],
            "工科试验班按宽口径工程大类初步归入机械、电气、信息、自动化、计算机、材料能源、土木和空天方向。",
        )
    return None


def _result(action: str, decision: str, direct: list[str], related: list[str], confidence: str, basis: str) -> dict[str, object]:
    direct = _valid_labels(direct)
    related = [label for label in _valid_labels(related) if label not in direct]
    return {
        "action": action,
        "decision": decision,
        "direct": direct,
        "related": related,
        "confidence": confidence,
        "basis": basis,
    }


def _valid_labels(labels: list[str]) -> list[str]:
    result = []
    for label in labels:
        if label in LABELS and label not in result:
            result.append(label)
    return result


def _source_url(school: str, registry: dict) -> str:
    if school.startswith("哈尔滨工业大学"):
        return "https://zsb.hit.edu.cn/article/read/35766a7f35b60e5737b4ab426ee28103"
    schools = registry.get("schools") or {}
    if school in schools:
        entry = schools[school]
        return str(entry.get("source_url") or entry.get("list_url") or "")
    base = school.split("(")[0].strip()
    if base in schools:
        entry = schools[base]
        return str(entry.get("source_url") or entry.get("list_url") or "")
    return f"https://gaokao.chsi.com.cn/zsgs/zhangcheng/listVerifedZszc.do?method=index&yxmc={quote(base)}"


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
