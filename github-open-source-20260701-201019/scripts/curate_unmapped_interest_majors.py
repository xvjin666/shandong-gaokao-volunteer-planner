from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

from gaokao_decision.database import connect, fetch_admissions
from gaokao_decision.scoring import INTEREST_LABELS


LABELS = set(INTEREST_LABELS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review and classify unmapped major names.")
    parser.add_argument("--db", default="data/local/gaokao.sqlite")
    parser.add_argument("--unmapped", default="data/processed/interest_major_unmapped_majors.csv")
    parser.add_argument("--review", default="data/processed/interest_major_manual_review.csv")
    parser.add_argument("--overrides", default="data/curated/interest_major_overrides.csv")
    args = parser.parse_args()

    with connect(args.db) as connection:
        admissions = fetch_admissions(connection)
    evidence = _major_evidence(admissions)
    majors = _read_unmapped(Path(args.unmapped))

    review_rows = []
    override_rows = []
    for index, major_name in enumerate(majors, 1):
        classification = classify_major(major_name)
        record = evidence.get(major_name, {})
        row = {
            "index": index,
            "major_name": major_name,
            "action": classification["action"],
            "decision": classification["decision"],
            "direct_interests": "、".join(classification["direct"]),
            "related_interests": "、".join(classification["related"]),
            "confidence": classification["confidence"],
            "rationale": classification["rationale"],
            "record_count": record.get("record_count", 0),
            "years": "、".join(str(year) for year in record.get("years", ())),
            "school_examples": "、".join(record.get("school_examples", ())),
        }
        review_rows.append(row)
        if classification["action"] == "map":
            override_rows.append({
                "major_name": major_name,
                "action": "map",
                "direct_interests": row["direct_interests"],
                "related_interests": row["related_interests"],
                "rationale": row["rationale"],
            })

    _write_csv(Path(args.review), review_rows, [
        "index",
        "major_name",
        "action",
        "decision",
        "direct_interests",
        "related_interests",
        "confidence",
        "rationale",
        "record_count",
        "years",
        "school_examples",
    ])
    _write_csv(Path(args.overrides), override_rows, [
        "major_name",
        "action",
        "direct_interests",
        "related_interests",
        "rationale",
    ])

    print({
        "review": args.review,
        "overrides": args.overrides,
        "review_count": len(review_rows),
        "override_count": len(override_rows),
        "manual_review_count": sum(1 for row in review_rows if row["action"] != "map"),
    })


def _read_unmapped(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [row["major_name"].strip() for row in csv.DictReader(file) if row.get("major_name")]


def _major_evidence(admissions) -> dict[str, dict[str, object]]:
    grouped: dict[str, list] = defaultdict(list)
    for record in admissions:
        grouped[record.major_name].append(record)
    evidence = {}
    for major_name, records in grouped.items():
        schools = []
        for record in records:
            if record.school_name and record.school_name not in schools:
                schools.append(record.school_name)
        evidence[major_name] = {
            "record_count": len(records),
            "years": tuple(sorted({record.year for record in records})),
            "school_examples": tuple(schools[:5]),
        }
    return evidence


def classify_major(name: str) -> dict[str, object]:
    mapped = _trial_class_rule(name) or _named_major_rule(name)
    if mapped:
        direct, related, rationale = mapped
        return _result("map", "纳入兴趣映射", direct, related, "high", rationale)

    if _is_broad_container(name):
        return _result(
            "review",
            "保留人工核验",
            [],
            [],
            "manual",
            "名称只给出学院、大类、通用试验班或预科身份，未说明最终分流专业；自动推荐会误导，必须看招生章程或专业分流说明。",
        )

    return _result(
        "review",
        "保留人工核验",
        [],
        [],
        "manual",
        "名称无法仅凭专业名稳定判断培养方向；暂不进入兴趣硬匹配，避免误推。",
    )


def _trial_class_rule(name: str) -> tuple[list[str], list[str], str] | None:
    if "试验班" not in name:
        return None
    rules = [
        (r"信息管理", ["信息管理与信息系统", "数据管理"], ["图书情报"], "试验班括号明确给出信息管理方向，按信息管理、数据管理和图书情报处理。"),
        (r"民航安全|应急", ["安全工程"], ["航空飞行", "公共管理"], "试验班括号明确给出民航安全或应急方向，按安全工程和航空管理相关处理。"),
        (r"自主智能系统|智能系统|智能类", ["人工智能", "自动化"], ["机器人工程", "计算机"], "试验班括号明确给出智能系统或智能类方向，按人工智能与自动化处理。"),
        (r"AI|图灵|计算与智能|智能与计算|未来信息|信息与智能|信息\)|信息创新|信息$|香农|华为", ["计算机", "人工智能"], ["软件", "数据科学", "电子信息"], "试验班括号给出信息、计算、AI 或图灵方向，按计算机与人工智能方向处理。"),
        (r"中欧航空|航空|航天|宇航|空天|飞行器", ["航空航天", "航空飞行"], ["机械", "自动化"], "试验班括号给出航空、航天、宇航或空天方向，按空天工程方向处理。"),
        (r"医学|医工|医理工|医药健康|生命科学与健康", ["医学", "生物医学工程"], ["生物科学", "药学"], "试验班括号给出医学、医工或生命健康方向，按医学/生物医学工程处理。"),
        (r"生物医药|生物制造|生命科学", ["生物科学", "药学"], ["生物医学工程"], "试验班括号给出生物、医药或生命科学方向，按生命科学与药学相关处理。"),
        (r"智慧化工|绿色化工|低碳工程|物质科学|纳米", ["化学", "应用化学", "材料"], ["环境工程", "新能源"], "试验班括号给出化工、物质科学或纳米方向，按化学/材料方向处理。"),
        (r"碳中和", ["能源", "新能源", "环境工程"], ["材料"], "试验班括号给出碳中和方向，按能源、环境和材料交叉方向处理。"),
        (r"建筑|建造|城市|规划|景观|创意设计", ["建筑学", "城乡规划", "土木"], ["设计", "风景园林"], "试验班括号给出建筑、建造、规划、景观或城市方向，按建筑土木方向处理。"),
        (r"机器人", ["机器人工程", "自动化"], ["人工智能", "机械"], "试验班括号给出机器人方向，按机器人/自动化方向处理。"),
        (r"智能网联汽车", ["车辆工程", "自动化"], ["人工智能", "交通"], "试验班括号给出智能网联汽车方向，按车辆工程和自动化处理。"),
        (r"智能化制造|智能过程|装备|精工|机电", ["机械", "自动化"], ["仪器测控"], "试验班括号给出制造、装备、过程或机电方向，按机械自动化方向处理。"),
        (r"智慧环境|生态环境|生态与环境|生态修复|资源环境|地球科学", ["环境工程", "生态学"], ["地质学", "地理科学"], "试验班括号给出环境、生态、地球科学或资源环境方向，按环境生态方向处理。"),
        (r"空间信息|智慧城市", ["测绘", "地理科学"], ["城乡规划", "计算机"], "试验班括号给出空间信息或智慧城市方向，按测绘地理信息方向处理。"),
        (r"数理", ["数学", "物理"], ["统计", "应用物理"], "试验班括号给出数理方向，按数学物理基础方向处理。"),
        (r"量子", ["物理", "应用物理"], ["电子信息"], "试验班括号给出量子科技方向，按物理和电子信息交叉方向处理。"),
        (r"数智经济|智能管理|管理类|管理学科|经济与管理|经管|经济管理|工商", ["经济学", "工商管理"], ["信息管理与信息系统", "数据管理"], "试验班括号给出经济、管理或经管方向，按财经管理方向处理。"),
        (r"电类", ["电气", "电子信息"], ["自动化"], "试验班括号给出电类专业预选，按电气电子方向处理。"),
        (r"海洋|舰船", ["海洋科学", "船舶"], ["机械"], "试验班括号给出海洋、舰船或海洋装备方向，按海洋工程方向处理。"),
        (r"食品", ["食品科学", "食品质量"], ["食品酿造"], "试验班括号给出食品健康与安全方向，按食品科学方向处理。"),
        (r"PLE", ["哲学", "法学", "经济学"], [], "PLE 通常指哲学、法学、经济学交叉试验班，按这三类兴趣处理。"),
        (r"外语交叉", ["外国语言文学", "小语种"], ["英语"], "试验班括号给出外语交叉方向，按外语类处理。"),
        (r"国务学院", ["公共管理", "政治学"], ["国际经济与贸易"], "试验班括号给出国务学院方向，按公共管理和政治学处理。"),
    ]
    for pattern, direct, related, rationale in rules:
        if re.search(pattern, name):
            return direct, related, rationale
    return None


def _named_major_rule(name: str) -> tuple[list[str], list[str], str] | None:
    rules = [
        (r"全媒体电商运营", ["电子商务"], ["网络与新媒体", "新闻传播", "会展传播"], "专业名明确是全媒体电商运营，按电子商务和新媒体运营处理。"),
        (r"包装设计|新媒体艺术|艺术与科技", ["设计"], ["数字媒体"], "专业名明确是设计/新媒体艺术方向，按设计和数字媒体处理。"),
        (r"城市设计|建筑设计|旅游规划与设计|建筑装饰工程", ["建筑学", "城乡规划", "设计"], ["土木"], "专业名明确是建筑、城市或规划设计方向。"),
        (r"播音与主持艺术", ["播音主持"], ["新闻传播"], "专业名明确为播音主持艺术。"),
        (r"影视技术|影视摄影与制作|电影制作|智能视听工程|智能视觉工程", ["戏剧影视", "数字媒体"], ["电子信息", "人工智能"], "专业名明确为影视、视听或视觉技术方向。"),
        (r"摄影", ["美术学", "数字媒体"], [], "专业名明确为摄影艺术方向。"),
        (r"时尚传播", ["新闻传播", "广告学"], ["设计"], "专业名明确为时尚传播，按传播和广告处理。"),
        (r"艺术学理论类", ["美术学", "音乐学", "戏剧影视"], [], "专业名为艺术学理论大类，归入艺术理论相关兴趣。"),
        (r"应用中文|秘书学", ["汉语言文学"], [], "专业名明确为中文应用或秘书写作方向。"),
        (r"应用外语|应用韩语|外国语言与外国历史|语言学|应用语言学|外事实务", ["外国语言文学", "小语种"], ["英语", "国际经济与贸易"], "专业名明确为外语、语言学或涉外事务方向。"),
        (r"图书馆学", ["图书情报"], ["信息管理与信息系统"], "专业名明确为图书馆学，归入图书情报。"),
        (r"数字人文", ["汉语言文学", "历史学"], ["数据管理", "图书情报"], "数字人文属于人文学科与数据方法交叉。"),
        (r"家庭教育|融合教育|戏剧教育|财务会计教育", ["教育学"], [], "专业名明确为教育方向。"),
        (r"女性学|工会学", ["社会学"], ["公共管理"], "专业名属于社会学与社会组织研究方向。"),
        (r"婚姻服务与管理|现代家政管理|慈善管理", ["社会工作"], ["公共管理"], "专业名明确为社会服务与公共服务管理方向。"),
        (r"城市管理|城市设施智慧管理|智慧社区管理|智慧健康养老管理|现代殡葬管理|自然资源登记与管理|药事管理|药品质量管理|药物经济与管理", ["公共管理"], ["社会工作"], "专业名明确为公共事务、城市社区、自然资源或医药事务管理方向。"),
        (r"婴幼儿发展与健康管理", ["学前教育"], ["护理学", "公共管理"], "专业名明确为婴幼儿发展与健康服务方向。"),
        (r"民航运输服务与管理|航空安防管理", ["交通", "航空飞行"], ["公共管理"], "专业名明确为民航运输或航空安防管理方向。"),
        (r"国际邮轮管理|烹饪与餐饮管理", ["旅游管理", "酒店管理"], ["食品科学"], "专业名明确为邮轮、餐饮或酒店旅游管理方向。"),
        (r"水路运输与海事管理|海事管理", ["交通"], ["公共管理"], "专业名明确为水路运输或海事管理方向。"),
        (r"经济与贸易类|经济工程", ["经济学", "国际经济与贸易"], [], "专业名明确为经济或贸易方向。"),
        (r"资产评估", ["金融", "会计学"], [], "专业名明确为资产评估，归入金融会计方向。"),
        (r"法律|监狱学|社区矫正", ["法学"], ["公安学", "社会工作"], "专业名明确为法律、监狱或矫正方向。"),
        (r"海外利益安全|海外安全管理", ["公安学", "法学"], ["政治学"], "专业名明确为海外安全治理方向。"),
        (r"安全生产监管|智慧应急|抢险救援指挥与技术|消防指挥|火灾勘查|核生化消防", ["安全工程"], ["公安学", "公共管理"], "专业名明确为安全监管、应急、消防或救援方向。"),
        (r"工业互联网技术", ["物联网", "自动化"], ["计算机", "电子信息"], "专业名明确为工业互联网技术。"),
        (r"工业智能|智能控制技术|智能无人系统技术|未来机器人|机器人技术|装备智能化技术", ["人工智能", "自动化", "机器人工程"], ["机械"], "专业名明确为工业智能、控制、无人系统或机器人方向。"),
        (r"智能工程与创意设计", ["设计", "工业设计"], ["自动化", "人工智能"], "专业名明确为智能工程与创意设计，按工业设计和智能工程交叉方向处理。"),
        (r"智能测控工程|现代测控工程技术|现代分析测试技术", ["仪器测控"], ["自动化", "电子信息"], "专业名明确为测控或分析测试技术方向。"),
        (r"数控技术|汽车工程技术|智能网联汽车工程技术|电梯工程技术", ["机械", "车辆工程"], ["自动化"], "专业名明确为机械、汽车或装备控制方向。"),
        (r"电信工程及管理|电磁场与无线技术", ["通信工程", "电子信息"], ["信息管理与信息系统"], "专业名明确为电信、无线或通信工程方向。"),
        (r"电机电器智能化|电缆工程|核电技术与控制工程", ["电气"], ["自动化", "能源"], "专业名明确为电气、电机、电缆或核电控制方向。"),
        (r"空间信息与数字技术", ["测绘", "计算机"], ["地理科学"], "专业名明确为空间信息与数字技术方向。"),
        (r"智能地球探测|地质类|土地整治工程|旅游地学与规划工程", ["地质学", "测绘"], ["矿业资源", "地理科学"], "专业名明确为地质、地学、土地整治或探测方向。"),
        (r"天文学|声学|空间科学与技术|系统科学与工程", ["物理", "应用物理"], ["数学"], "专业名明确为基础理科或系统科学方向。"),
        (r"智慧气象技术", ["大气科学"], ["数据科学"], "专业名明确为气象技术方向。"),
        (r"海洋机器人|智能海洋装备|海洋资源开发技术", ["海洋科学", "船舶"], ["机器人工程", "机械"], "专业名明确为海洋装备、机器人或海洋资源开发方向。"),
        (r"市政工程|建筑类|建筑设计|道路与桥梁工程|铁道工程", ["土木", "交通"], ["建筑学"], "专业名明确为土建、市政、道路桥梁或铁道工程方向。"),
        (r"智能运输工程|道路与桥梁工程|铁道机车智能运用技术", ["交通"], ["车辆工程", "自动化"], "专业名明确为交通运输、道路桥梁或铁道机车方向。"),
        (r"水务工程|水质科学与技术", ["水利", "环境工程"], [], "专业名明确为水务或水质工程方向。"),
        (r"氢能科学与工程|碳储科学与工程|煤炭清洁利用工程|核工程类|核化工与核燃料工程|辐射防护与核安全", ["能源", "新能源"], ["环境工程", "安全工程", "应用化学"], "专业名明确为能源、核能、氢能、碳储或核安全方向。"),
        (r"武器发射工程|武器系统与工程", ["兵器"], ["机械", "自动化"], "专业名明确为兵器工程方向。"),
        (r"服装工程技术", ["服装设计"], ["材料"], "专业名明确为服装工程技术。"),
        (r"林产化工|涂料工程|精细化工|现代精细化工技术|资源循环科学与工程", ["应用化学"], ["材料", "环境工程"], "专业名明确为化工、涂料、精细化工或资源循环工程。"),
        (r"咖啡科学与工程|白酒酿造工程", ["食品科学", "食品酿造"], ["农学"], "专业名明确为咖啡或白酒酿造工程，归入食品与酿造。"),
        (r"法医学|眼视光学|眼视光技术|妇幼保健医学|老年医学与健康|听力与言语康复学|康复作业治疗|康复工程|康复辅助器具技术|职业病危害检测评价技术", ["医学", "康复治疗"], ["预防医学"], "专业名明确为医学、康复、眼视光或职业健康方向。"),
        (r"护理$", ["护理学"], [], "专业名为护理，等同护理学方向。"),
        (r"药物经济与管理", ["药学", "公共管理"], [], "专业名明确为药物经济与管理。"),
        (r"神经科学", ["生物科学", "基础医学"], [], "专业名明确为神经科学。"),
        (r"生态修复学|湿地保护与恢复|野生动物与自然保护区管理", ["生态学", "环境工程"], ["动物科学", "公共管理"], "专业名明确为生态修复、湿地保护或自然保护区管理。"),
        (r"智能化农业装备技术|现代畜牧|现代种业技术|生物农药科学与工程|生物育种技术|种子科学与工程|菌物科学与工程|蜂学|经济动物学|饲料工程", ["农学", "动物科学"], ["生物科学", "食品科学", "植物保护"], "专业名明确为农业、畜牧、种业、菌物、蜂学或饲料方向。"),
        (r"生物质科学与工程", ["生物科学", "能源"], ["材料", "环境工程"], "专业名明确为生物质科学与工程，按生物、能源和材料交叉方向处理。"),
        (r"森林保护|森林工程|经济林", ["林学"], ["生态学"], "专业名明确为森林、林业工程或经济林方向。"),
        (r"钢铁智能轧制技术", ["冶金", "材料"], ["自动化"], "专业名明确为钢铁轧制和冶金材料方向。"),
        (r"轻工类", ["材料", "应用化学"], ["食品科学"], "专业名为轻工类，按轻工材料和应用化学处理。"),
    ]
    for pattern, direct, related, rationale in rules:
        if re.search(pattern, name):
            return direct, related, rationale
    return None


def _is_broad_container(name: str) -> bool:
    if "本科预科班" in name:
        return True
    if re.search(r"商学院|文学与社会科学院|理工学院", name):
        return True
    if re.search(r"试验班", name):
        return True
    if name in {"自然科学试验班", "自然科学试验班(拔尖学生培养基地)"}:
        return True
    return False


def _result(action: str, decision: str, direct: list[str], related: list[str], confidence: str, rationale: str) -> dict[str, object]:
    direct = _valid_labels(direct)
    related = [label for label in _valid_labels(related) if label not in direct]
    return {
        "action": action,
        "decision": decision,
        "direct": direct,
        "related": related,
        "confidence": confidence,
        "rationale": rationale,
    }


def _valid_labels(labels: list[str]) -> list[str]:
    result = []
    for label in labels:
        if label in LABELS and label not in result:
            result.append(label)
    return result


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
