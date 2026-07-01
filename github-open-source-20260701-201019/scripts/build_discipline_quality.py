from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FOURTH_ROUND_SOURCE = {
    "source_id": "moe_cdgdc_fourth_round_discipline_assessment_2017",
    "assessment_round": "第四轮",
    "source_type": "official_public_result",
    "source": "教育部学位与研究生教育发展中心全国第四轮学科评估结果公布",
    "source_url": "https://www.cdgdc.edu.cn/dslxkpgjggb/",
    "structured_copy_url": "https://github.com/Johnnydaszhu/2017ChinaUniversityDisciplineAssessment",
}

FIFTH_ROUND_SOURCE = {
    "source_id": "fifth_round_network_compilation_gaokaozhitongche_2023",
    "assessment_round": "第五轮",
    "source_type": "network_compilation_not_official_full_release",
    "source": "高考直通车转载整理的教育部第五轮学科评估情况汇总",
    "source_url": "https://app.gaokaozhitongche.com/news/h/v2PPjjj2",
    "note": "第五轮学科评估未发现教育部/学位中心全量官方公开表。本源为网络汇编，页面亦提示信息总结自校方资讯、网络等途径且为不完全统计。",
}

FIFTH_ROUND_CROSSCHECK_SOURCE = {
    "source_id": "fifth_round_network_compilation_acabridge_2023",
    "assessment_round": "第五轮",
    "source_type": "network_compilation_not_official_full_release",
    "source": "学术桥转载整理的部分 985 高校第五轮学科评估结果汇总",
    "source_url": "https://www.acabridge.cn/news/202304/t20230430_2389587.shtml",
    "note": "作为第五轮网络汇编交叉证据归档；正文开头提示最终结果以官方为准。",
}

FIFTH_ROUND_IMAGE_ARCHIVE_SOURCE = {
    "source_id": "fifth_round_network_compilation_baai_datawhale_2025",
    "assessment_round": "第五轮",
    "source_type": "network_compilation_not_official_full_release",
    "source": "Datawhale 高校转载/整理的第五轮学科评估 A 类专业汇总图片",
    "source_url": "https://hub.baai.ac.cn/view/42971",
    "note": "第五轮学科评估未发现教育部/学位中心全量官方公开表。本源仅归档为图片汇总证据。",
}


DISCIPLINE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "哲学": ("哲学",),
    "理论经济学": ("经济学", "经济", "理论经济学"),
    "应用经济学": ("经济学", "金融", "财政学", "税收学", "国际经济与贸易", "经济统计", "数字经济", "应用经济学"),
    "法学": ("法学", "知识产权", "国际法", "纪检监察"),
    "政治学": ("政治学", "国际政治", "外交学", "思想政治教育"),
    "社会学": ("社会学", "社会工作", "家政学"),
    "民族学": ("民族学",),
    "马克思主义理论": ("马克思主义理论", "思想政治教育", "中国共产党历史"),
    "教育学": ("教育学", "学前教育", "小学教育", "特殊教育", "教育技术学"),
    "心理学": ("心理学", "应用心理学"),
    "体育学": ("体育", "体育教育", "运动训练", "运动康复", "体育学"),
    "中国语言文学": ("汉语言文学", "汉语言", "中国语言文学", "汉语国际教育", "古典文献学"),
    "外国语言文学": ("英语", "翻译", "商务英语", "外国语言文学", "日语", "俄语", "德语", "法语", "西班牙语"),
    "新闻传播学": ("新闻学", "传播学", "新闻传播", "网络与新媒体", "广告学", "编辑出版学"),
    "考古学": ("考古学", "文物", "文化遗产"),
    "中国史": ("历史学", "中国史"),
    "世界史": ("历史学", "世界史"),
    "数学": ("数学", "数学与应用数学", "信息与计算科学", "数据计算及应用"),
    "物理学": ("物理学", "应用物理学", "物理"),
    "化学": ("化学", "应用化学"),
    "天文学": ("天文学",),
    "地理学": ("地理科学", "地理信息科学", "自然地理与资源环境", "人文地理与城乡规划"),
    "大气科学": ("大气科学", "应用气象学", "气象"),
    "海洋科学": ("海洋科学", "海洋技术", "海洋资源与环境"),
    "地球物理学": ("地球物理学", "空间科学与技术"),
    "地质学": ("地质学", "古生物学"),
    "生物学": ("生物科学", "生物技术", "生物信息", "生物学"),
    "系统科学": ("系统科学", "系统工程"),
    "科学技术史": ("科学技术史",),
    "生态学": ("生态学",),
    "统计学": ("统计学", "应用统计学", "经济统计学", "统计"),
    "力学": ("力学", "工程力学", "理论与应用力学"),
    "机械工程": ("机械", "机械工程", "机械设计制造及其自动化", "车辆工程", "智能制造工程"),
    "光学工程": ("光电信息", "光学工程", "光电信息科学与工程"),
    "仪器科学与技术": ("测控技术与仪器", "智能感知工程", "仪器", "精密仪器"),
    "材料科学与工程": ("材料", "材料科学与工程", "材料物理", "材料化学", "新能源材料与器件"),
    "冶金工程": ("冶金工程", "冶金"),
    "动力工程及工程热物理": ("能源与动力工程", "动力工程", "储能科学与工程"),
    "电气工程": ("电气工程", "电气工程及其自动化", "智能电网信息工程", "电气"),
    "电子科学与技术": ("电子科学与技术", "电子信息", "微电子", "集成电路", "电子封装技术"),
    "信息与通信工程": ("通信工程", "信息工程", "电子信息工程", "电波传播", "水声工程"),
    "控制科学与工程": ("自动化", "机器人工程", "智能装备", "控制科学与工程"),
    "计算机科学与技术": ("计算机", "计算机科学与技术", "数据科学与大数据技术", "人工智能", "智能科学与技术"),
    "建筑学": ("建筑学", "历史建筑保护工程"),
    "土木工程": ("土木工程", "智能建造", "给排水科学与工程", "道路桥梁与渡河工程"),
    "水利工程": ("水利水电工程", "水文与水资源工程", "港口航道与海岸工程", "水利"),
    "测绘科学与技术": ("测绘工程", "遥感科学与技术", "导航工程", "地理空间信息工程"),
    "化学工程与技术": ("化学工程与工艺", "化工与制药", "制药工程", "化工"),
    "地质资源与地质工程": ("资源勘查工程", "地质工程", "勘查技术与工程"),
    "矿业工程": ("采矿工程", "矿物加工工程", "矿业"),
    "石油与天然气工程": ("石油工程", "油气储运工程", "海洋油气工程"),
    "纺织科学与工程": ("纺织工程", "服装设计与工程", "非织造材料与工程"),
    "轻工技术与工程": ("轻化工程", "包装工程", "印刷工程"),
    "交通运输工程": ("交通运输", "交通工程", "飞行技术", "航海技术", "轮机工程"),
    "船舶与海洋工程": ("船舶与海洋工程", "海洋工程与技术"),
    "航空宇航科学与技术": ("航空航天", "飞行器设计与工程", "飞行器制造工程", "飞行器动力工程"),
    "兵器科学与技术": ("武器系统", "弹药工程", "探测制导", "信息对抗技术", "兵器"),
    "核科学与技术": ("核工程与核技术", "辐射防护与核安全", "核化工与核燃料工程"),
    "农业工程": ("农业工程", "农业机械化及其自动化", "农业水利工程"),
    "林业工程": ("林业工程", "木材科学与工程", "林产化工"),
    "环境科学与工程": ("环境科学", "环境工程", "环境生态工程", "环保设备工程"),
    "生物医学工程": ("生物医学工程", "假肢矫形工程"),
    "食品科学与工程": ("食品科学与工程", "食品质量与安全", "酿酒工程", "食品营养与健康"),
    "城乡规划学": ("城乡规划", "人文地理与城乡规划"),
    "风景园林学": ("风景园林", "园林"),
    "软件工程": ("软件工程", "软件"),
    "安全科学与工程": ("安全工程", "应急技术与管理", "职业卫生工程"),
    "网络空间安全": ("网络空间安全", "信息安全", "密码科学与技术"),
    "作物学": ("农学", "种子科学与工程", "智慧农业"),
    "园艺学": ("园艺", "设施农业科学与工程"),
    "农业资源与环境": ("农业资源与环境",),
    "植物保护": ("植物保护", "植物科学与技术"),
    "畜牧学": ("动物科学", "智慧牧业科学与工程"),
    "兽医学": ("动物医学", "动植物检疫"),
    "林学": ("林学", "森林保护"),
    "水产": ("水产养殖学", "海洋渔业科学与技术", "水产"),
    "草学": ("草业科学", "草坪科学与工程"),
    "基础医学": ("基础医学", "生物医学科学"),
    "临床医学": ("临床医学", "麻醉学", "医学影像学", "儿科学", "精神医学", "眼视光医学"),
    "口腔医学": ("口腔医学",),
    "公共卫生与预防医学": ("预防医学", "食品卫生与营养学", "卫生检验与检疫", "公共卫生"),
    "中医学": ("中医学", "针灸推拿学", "中医康复学", "中医养生学"),
    "中西医结合": ("中西医临床医学", "中西医结合"),
    "药学": ("药学", "药物制剂", "临床药学", "药物分析"),
    "中药学": ("中药学", "中药资源与开发"),
    "护理学": ("护理学", "助产学"),
    "管理科学与工程": ("信息管理与信息系统", "工程管理", "工程造价", "大数据管理与应用", "管理科学"),
    "工商管理": ("工商管理", "市场营销", "会计学", "财务管理", "人力资源管理", "审计学"),
    "农林经济管理": ("农林经济管理", "农村区域发展"),
    "公共管理": ("公共事业管理", "行政管理", "劳动与社会保障", "土地资源管理", "健康服务与管理"),
    "图书情报与档案管理": ("图书馆学", "档案学", "信息资源管理", "图书情报"),
    "艺术学理论": ("艺术史论", "艺术管理", "艺术学理论"),
    "音乐与舞蹈学": ("音乐学", "舞蹈学", "音乐表演"),
    "戏剧与影视学": ("戏剧影视", "广播电视编导", "播音与主持艺术", "动画", "电影学"),
    "美术学": ("美术学", "绘画", "雕塑", "书法学"),
    "设计学": ("设计学", "视觉传达设计", "环境设计", "产品设计", "数字媒体艺术", "工业设计"),
}


DISCIPLINE_ALIASES = {
    "马理": "马克思主义理论",
    "马克思理论": "马克思主义理论",
    "马克思主义理论学": "马克思主义理论",
    "中文": "中国语言文学",
    "外语": "外国语言文学",
    "新闻传播": "新闻传播学",
    "公共卫生": "公共卫生与预防医学",
    "公管": "公共管理",
    "管科": "管理科学与工程",
    "工商管理学": "工商管理",
    "农林经济": "农林经济管理",
    "农林经济管理学": "农林经济管理",
    "图书情报": "图书情报与档案管理",
    "信息资源管理": "图书情报与档案管理",
    "数学学科": "数学",
    "物理": "物理学",
    "物理雪": "物理学",
    "地学": "地质学",
    "生态": "生态学",
    "生物": "生物学",
    "计算机": "计算机科学与技术",
    "软件": "软件工程",
    "光工": "光学工程",
    "材料": "材料科学与工程",
    "材料科学与技术": "材料科学与工程",
    "机械": "机械工程",
    "控制": "控制科学与工程",
    "自动化": "控制科学与工程",
    "能动": "动力工程及工程热物理",
    "能源动力与工程": "动力工程及工程热物理",
    "动力工程及热物理": "动力工程及工程热物理",
    "动力工程": "动力工程及工程热物理",
    "电子科学技术": "电子科学与技术",
    "信息与工程": "信息与通信工程",
    "网络安全": "网络空间安全",
    "网络安全安全": "网络空间安全",
    "测绘学科与技术": "测绘科学与技术",
    "化工": "化学工程与技术",
    "核科学": "核科学与技术",
    "安全科学": "安全科学与工程",
    "环境管理与科学": "环境科学与工程",
    "环境科学": "环境科学与工程",
    "土木": "土木工程",
    "交通运输": "交通运输工程",
    "船舶": "船舶与海洋工程",
    "航空宇航": "航空宇航科学与技术",
    "风景园林": "风景园林学",
    "农业资源": "农业资源与环境",
    "公共卫生与预防医学学": "公共卫生与预防医学",
    "基础医学学": "基础医学",
    "临床医学学": "临床医学",
    "口腔": "口腔医学",
    "护理": "护理学",
    "中西医结合医学": "中西医结合",
    "艺术学": "艺术学理论",
    "戏剧艺术": "戏剧与影视学",
    "电影艺术": "戏剧与影视学",
    "广播电视艺术": "戏剧与影视学",
    "食品科学": "食品科学与工程",
}

GRADE_LABELS = ("A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def keywords_for_discipline(discipline: str) -> str:
    values: list[str] = []
    for item in (discipline, *DISCIPLINE_KEYWORDS.get(discipline, ())):
        item = item.strip()
        if item and item not in values:
            values.append(item)
    return ",".join(values)


def plain_text_from_html(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonical_discipline(value: str) -> str:
    item = value.strip()
    item = re.sub(r"[（(][^）)]*[）)]", "", item)
    item = re.sub(r"\s+", "", item)
    item = item.strip("。；;、，,：:")
    if not item:
        return ""
    if item in DISCIPLINE_KEYWORDS:
        return item
    if item in DISCIPLINE_ALIASES:
        return DISCIPLINE_ALIASES[item]
    if item.endswith("学科") and item[:-2] in DISCIPLINE_KEYWORDS:
        return item[:-2]
    for discipline in sorted(DISCIPLINE_KEYWORDS, key=len, reverse=True):
        if item == discipline.replace("与", ""):
            return discipline
    return ""


def split_discipline_items(value: str) -> list[str]:
    text = value
    text = text.replace("和", "、")
    text = text.replace("及", "、")
    text = text.replace("，", "、").replace(",", "、").replace("；", "、").replace(";", "、")
    items: list[str] = []
    for item in text.split("、"):
        canonical = canonical_discipline(item)
        if canonical and canonical not in items:
            items.append(canonical)
    return items


def known_school_names(fourth_rows: list[dict[str, str]]) -> list[str]:
    names = {row["school_name"] for row in fourth_rows}
    names.update(
        {
            "中国石油大学（北京）",
            "华北水利水电大学",
            "南京艺术学院",
            "广州医科大学",
            "景德镇陶瓷大学",
        }
    )
    return sorted(names, key=len, reverse=True)


def fifth_round_school_blocks(text: str, schools: list[str]) -> list[tuple[str, str]]:
    escaped = "|".join(re.escape(name) for name in schools)
    marker = re.compile(rf"(?<![\u4e00-\u9fff])({escaped})(?= (?:据悉|1、|马克思主义理论学科较|A\+学科))")
    matches = list(marker.finditer(text))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if "学科" in block:
            blocks.append((match.group(1), block))
    return blocks


def build_fifth_round_rows(source_html: Path, fourth_rows: list[dict[str, str]], updated_at: str) -> list[dict[str, str]]:
    text = plain_text_from_html(source_html)
    schools = known_school_names(fourth_rows)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    grade_pattern = re.compile(
        r"(?:^| )\d+、(A\+|A-|A|B\+|B-|B|C\+|C-|C)类?学科 "
        r"(.*?)(?= (?:\d+、(?:A\+|A-|A|B\+|B-|B|C\+|C-|C)类?学科|“211”高校|其他本科高校|车车特别提醒|登录高考|$))"
    )
    for school, block in fifth_round_school_blocks(text, schools):
        for match in grade_pattern.finditer(block):
            grade = match.group(1)
            for discipline in split_discipline_items(match.group(2)):
                key = (school, discipline, grade)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "school_name": school,
                        "major_keywords": keywords_for_discipline(discipline),
                        "discipline": discipline,
                        "assessment_grade": grade,
                        "postgraduate_recommend_rate": "",
                        "source": FIFTH_ROUND_SOURCE["source"],
                        "source_url": FIFTH_ROUND_SOURCE["source_url"],
                        "updated_at": updated_at,
                        "assessment_round": FIFTH_ROUND_SOURCE["assessment_round"],
                        "discipline_code": "",
                        "source_id": FIFTH_ROUND_SOURCE["source_id"],
                        "source_type": FIFTH_ROUND_SOURCE["source_type"],
                        "confidence": "network_compilation",
                        "note": FIFTH_ROUND_SOURCE["note"],
                    }
                )
    return rows


def build_fourth_round_rows(source_csv: Path, updated_at: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with source_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            code = str(row.get("一级学科代码") or "").strip()
            discipline = str(row.get("一级学科名称") or "").strip()
            grade = str(row.get("评估结果") or "").strip()
            if not code or not discipline or not grade:
                continue
            for key, value in row.items():
                if not str(key or "").startswith("学校名称"):
                    continue
                school = str(value or "").strip()
                if not school:
                    continue
                rows.append(
                    {
                        "school_name": school,
                        "major_keywords": keywords_for_discipline(discipline),
                        "discipline": discipline,
                        "assessment_grade": grade,
                        "postgraduate_recommend_rate": "",
                        "source": FOURTH_ROUND_SOURCE["source"],
                        "source_url": FOURTH_ROUND_SOURCE["source_url"],
                        "updated_at": updated_at,
                        "assessment_round": FOURTH_ROUND_SOURCE["assessment_round"],
                        "discipline_code": code,
                        "source_id": FOURTH_ROUND_SOURCE["source_id"],
                        "source_type": FOURTH_ROUND_SOURCE["source_type"],
                        "confidence": "official",
                        "note": "",
                    }
                )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "school_name",
        "major_keywords",
        "discipline",
        "assessment_grade",
        "postgraduate_recommend_rate",
        "source",
        "source_url",
        "updated_at",
        "assessment_round",
        "discipline_code",
        "source_id",
        "source_type",
        "confidence",
        "note",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def grade_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["assessment_grade"]] = counts.get(row["assessment_grade"], 0) + 1
    return dict(sorted(counts.items(), key=lambda item: GRADE_LABELS.index(item[0]) if item[0] in GRADE_LABELS else 99))


def source_manifest(
    raw_fourth: Path,
    raw_fifth: Path,
    fifth_crosscheck: Path | None,
    fifth_manifest: Path | None,
    rows: list[dict[str, str]],
) -> dict[str, object]:
    fourth_rows = [row for row in rows if row["source_id"] == FOURTH_ROUND_SOURCE["source_id"]]
    fifth_rows = [row for row in rows if row["source_id"] == FIFTH_ROUND_SOURCE["source_id"]]
    payload: dict[str, object] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": [
            {
                **FOURTH_ROUND_SOURCE,
                "local_path": str(raw_fourth.relative_to(ROOT)),
                "sha256": sha256_file(raw_fourth),
                "structured_rows": len(fourth_rows),
                "disciplines": len({row["discipline"] for row in fourth_rows}),
                "schools": len({row["school_name"] for row in fourth_rows}),
                "grade_counts": grade_counts(fourth_rows),
            },
            {
                **FIFTH_ROUND_SOURCE,
                "local_path": str(raw_fifth.relative_to(ROOT)),
                "sha256": sha256_file(raw_fifth),
                "structured_rows": len(fifth_rows),
                "disciplines": len({row["discipline"] for row in fifth_rows}),
                "schools": len({row["school_name"] for row in fifth_rows}),
                "grade_counts": grade_counts(fifth_rows),
            },
            FIFTH_ROUND_CROSSCHECK_SOURCE,
            FIFTH_ROUND_IMAGE_ARCHIVE_SOURCE,
        ],
        "policy": {
            "fourth_round": "作为官方公开全量学科评估等级接入推荐展示。",
            "fifth_round": "未发现教育部/学位中心全量官方公开表；仅接入可从网页正文解析出学校、学科、等级的网络汇编项，并在记录中保留 network_compilation 标记。",
        },
    }
    if fifth_crosscheck and fifth_crosscheck.exists():
        payload["sources"][2] = {
            **FIFTH_ROUND_CROSSCHECK_SOURCE,
            "local_path": str(fifth_crosscheck.relative_to(ROOT)),
            "sha256": sha256_file(fifth_crosscheck),
        }
    if fifth_manifest and fifth_manifest.exists():
        try:
            fifth_payload = json.loads(fifth_manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fifth_payload = {}
        payload["sources"][3] = {
            **FIFTH_ROUND_IMAGE_ARCHIVE_SOURCE,
            "local_manifest": str(fifth_manifest.relative_to(ROOT)),
            "image_count": len(fifth_payload.get("unique_images") or []),
        }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build curated discipline assessment quality data.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--fourth-raw", default="data/raw/discipline/fourth_round_github_2017.csv")
    parser.add_argument("--fifth-raw", default="data/raw/discipline/fifth_round_structured/gaokaozhitongche_2023.html")
    parser.add_argument("--fifth-crosscheck", default="data/raw/discipline/fifth_round_structured/acabridge_2023.html")
    parser.add_argument("--fifth-manifest", default="data/raw/discipline/fifth_round_baai_images/manifest.json")
    parser.add_argument("--output", default="data/curated/discipline_quality.csv")
    parser.add_argument("--sources-output", default="data/curated/discipline_quality_sources.json")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    raw_fourth = root / args.fourth_raw
    raw_fifth = root / args.fifth_raw
    fifth_crosscheck = root / args.fifth_crosscheck
    fifth_manifest = root / args.fifth_manifest
    updated_at = datetime.now().date().isoformat()

    fourth_rows = build_fourth_round_rows(raw_fourth, updated_at)
    fifth_rows = build_fifth_round_rows(raw_fifth, fourth_rows, updated_at)
    rows = [*fourth_rows, *fifth_rows]
    rows.sort(key=lambda item: (item["school_name"], item["discipline_code"], item["assessment_grade"]))
    output = root / args.output
    write_csv(output, rows)

    sources_output = root / args.sources_output
    sources_output.parent.mkdir(parents=True, exist_ok=True)
    sources_output.write_text(
        json.dumps(
            source_manifest(raw_fourth, raw_fifth, fifth_crosscheck, fifth_manifest, rows),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"discipline_quality rows: {len(rows)} -> {output}")
    print(f"source manifest -> {sources_output}")


if __name__ == "__main__":
    main()
