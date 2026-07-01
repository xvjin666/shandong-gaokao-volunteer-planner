from __future__ import annotations

import argparse
import html
import json
from dataclasses import asdict
from pathlib import Path

from gaokao_decision.database import connect, fetch_admissions, list_batches
from gaokao_decision.models import CandidateProfile
from gaokao_decision.plan import build_volunteer_plan_from_recommendations
from gaokao_decision.recommend import recommend


STRATEGY_LABELS = {
    "aggressive": "激进版",
    "balanced": "均衡版",
    "conservative": "保守版",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a static HTML report from the local Gaokao DB.")
    parser.add_argument("--db", default="data/local/gaokao.sqlite")
    parser.add_argument("--output", default="reports/latest.html")
    parser.add_argument("--score", type=int, required=True)
    parser.add_argument("--rank", type=int, required=True)
    parser.add_argument("--subjects", nargs="+", required=True)
    parser.add_argument("--interests", nargs="*", default=[])
    parser.add_argument("--avoid", nargs="*", default=[])
    parser.add_argument("--max-tuition", type=int)
    parser.add_argument("--target-size", type=int, default=96)
    parser.add_argument("--allow-private", action="store_true")
    parser.add_argument("--allow-sino-foreign", action="store_true")
    args = parser.parse_args()

    candidate = CandidateProfile(
        score=args.score,
        rank=args.rank,
        subjects=tuple(args.subjects),
        interests=tuple(args.interests),
        avoid_keywords=tuple(args.avoid),
        max_tuition=args.max_tuition,
        allow_private=args.allow_private,
        allow_sino_foreign=args.allow_sino_foreign,
    )
    with connect(args.db) as connection:
        records = fetch_admissions(connection)
        batches = list_batches(connection)

    recommendations, rejections = recommend(records, candidate, limit=100000)
    plans = {
        strategy: build_volunteer_plan_from_recommendations(
            recommendations,
            rejections,
            strategy=strategy,
            target_size=args.target_size,
        )
        for strategy in STRATEGY_LABELS
    }
    payload = {
        "candidate": asdict(candidate),
        "recordCount": len(records),
        "batches": batches,
        "strategies": {
            key: {
                "label": STRATEGY_LABELS[key],
                "targetSize": plan.target_size,
                "quotas": plan.quotas,
                "riskCounts": plan.risk_counts,
                "warnings": plan.warnings,
                "recommendations": [asdict(item) for item in plan.recommendations],
                "rejectionsTotal": len(plan.rejections),
            }
            for key, plan in plans.items()
        },
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(payload), encoding="utf-8")
    print(output.resolve())


def render_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    escaped_json = data_json.replace("</", "<\\/")
    title = "山东高考志愿决策报告"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --ink: #17211f;
      --muted: #65706b;
      --line: #d9dfdc;
      --paper: #f7f8f5;
      --panel: #ffffff;
      --accent: #0f7b6c;
      --accent-2: #9b5c1d;
      --danger: #b33a3a;
      --warn: #be6b16;
      --steady: #2f6f9f;
      --safe: #3f7f4a;
      --shadow: 0 10px 30px rgba(35, 48, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      line-height: 1.5;
    }}
    .shell {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
    header {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 18px;
      align-items: end;
      padding: 22px 0 18px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{ margin: 0; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; letter-spacing: 0; }}
    .subtle {{ color: var(--muted); font-size: 14px; }}
    .stamp {{ text-align: right; color: var(--muted); font-size: 13px; }}
    .notice {{
      margin: 18px 0;
      padding: 12px 14px;
      border: 1px solid #ead2ad;
      background: #fff8ec;
      color: #68410d;
      border-radius: 8px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(130px, 1fr));
      gap: 12px;
      margin: 18px 0;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      box-shadow: var(--shadow);
    }}
    .metric b {{ display: block; font-size: 22px; }}
    .metric span {{ color: var(--muted); font-size: 13px; }}
    .toolbar {{
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      margin: 20px 0 12px;
      flex-wrap: wrap;
    }}
    .tabs, .filters {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    button, input {{
      height: 38px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 8px;
      padding: 0 12px;
      font: inherit;
    }}
    button {{ cursor: pointer; }}
    button.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    input {{ min-width: 260px; }}
    .layout {{
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }}
    aside, main {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }}
    aside {{ padding: 16px; position: sticky; top: 16px; }}
    main {{ overflow: hidden; }}
    .bar {{
      display: grid;
      grid-template-columns: 72px 1fr 42px;
      gap: 8px;
      align-items: center;
      margin: 9px 0;
      font-size: 13px;
    }}
    .track {{ height: 10px; background: #edf0ed; border-radius: 999px; overflow: hidden; }}
    .fill {{ height: 100%; border-radius: inherit; }}
    .risk-高冲 {{ background: var(--danger); }}
    .risk-冲 {{ background: var(--warn); }}
    .risk-稳中偏冲 {{ background: var(--accent-2); }}
    .risk-稳 {{ background: var(--steady); }}
    .risk-保 {{ background: var(--safe); }}
    .risk-强保 {{ background: #6b8d3e; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ background: #f1f3ef; text-align: left; font-size: 13px; color: #3d4844; }}
    td {{ font-size: 14px; }}
    .rank {{ width: 54px; color: var(--muted); }}
    .option {{ width: 28%; font-weight: 650; }}
    .risk {{ width: 90px; }}
    .score {{ width: 130px; }}
    .evidence {{ width: 32%; }}
    .pill {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 9px;
      border-radius: 999px;
      color: #fff;
      font-size: 12px;
      white-space: nowrap;
    }}
    details {{ margin-top: 6px; }}
    summary {{ cursor: pointer; color: var(--accent); font-weight: 600; }}
    .mini {{ color: var(--muted); font-size: 12px; }}
    .evidence-list {{ margin: 8px 0 0; padding-left: 18px; }}
    .evidence-list li {{ margin: 3px 0; }}
    .empty {{ padding: 34px; color: var(--muted); text-align: center; }}
    .warnings {{ margin: 0 0 14px; padding-left: 20px; color: #68410d; }}
    @media (max-width: 980px) {{
      .shell {{ padding: 14px; }}
      header {{ grid-template-columns: 1fr; }}
      .stamp {{ text-align: left; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .layout {{ grid-template-columns: 1fr; }}
      aside {{ position: static; }}
      table, thead, tbody, tr, th, td {{ display: block; width: 100% !important; }}
      thead {{ display: none; }}
      tr {{ border-bottom: 1px solid var(--line); }}
      td {{ border-bottom: 0; }}
      td::before {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 2px; }}
      td.rank::before {{ content: "序号"; }}
      td.option::before {{ content: "志愿"; }}
      td.risk::before {{ content: "风险"; }}
      td.score::before {{ content: "参考位次"; }}
      td.evidence::before {{ content: "依据"; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>{html.escape(title)}</h1>
        <div class="subtle" id="candidateLine"></div>
      </div>
      <div class="stamp" id="dataLine"></div>
    </header>

    <div class="notice">当前页面基于 2023-2025 官方投档数据生成。历史投档表不含完整 2026 招生计划、选科、体检、语种、学费和校区备注，正式填报前必须接入并复核这些硬性条件。</div>

    <section class="metrics" id="metrics"></section>

    <div class="toolbar">
      <div class="tabs" id="strategyTabs"></div>
      <div class="filters" id="riskFilters"></div>
      <input id="search" type="search" placeholder="搜索院校或专业">
    </div>

    <div class="layout">
      <aside>
        <h2>风险分布</h2>
        <div id="riskBars"></div>
        <h2 style="margin-top:22px;">方案提醒</h2>
        <ul class="warnings" id="warnings"></ul>
        <div class="mini" id="quotaLine"></div>
      </aside>
      <main>
        <table>
          <thead>
            <tr>
              <th class="rank">序号</th>
              <th class="option">专业 + 院校</th>
              <th class="risk">风险</th>
              <th class="score">参考位次</th>
              <th class="evidence">决策依据</th>
            </tr>
          </thead>
          <tbody id="rows"></tbody>
        </table>
        <div class="empty" id="empty" hidden>没有匹配当前筛选的志愿。</div>
      </main>
    </div>
  </div>

  <script id="report-data" type="application/json">{escaped_json}</script>
  <script>
    const report = JSON.parse(document.getElementById('report-data').textContent);
    const riskOrder = ['全部', '高冲', '冲', '稳中偏冲', '稳', '保', '强保', '证据不足'];
    let activeStrategy = 'balanced';
    let activeRisk = '全部';

    function riskClass(name) {{
      return 'risk-' + name.replaceAll(' ', '');
    }}

    function fmt(value) {{
      if (value === null || value === undefined || value === '') return '待接入';
      return String(Math.round(Number(value))).replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ',');
    }}

    function renderShell() {{
      const c = report.candidate;
      document.getElementById('candidateLine').textContent =
        `${{c.score}} 分 / 位次 ${{fmt(c.rank)}} / 选科 ${{c.subjects.join('、')}} / 偏好 ${{c.interests.join('、') || '未填写'}}`;
      document.getElementById('dataLine').textContent =
        `官方投档记录 ${{fmt(report.recordCount)}} 条 · 导入批次 ${{report.batches.length}} 个`;

      document.getElementById('strategyTabs').innerHTML = Object.entries(report.strategies).map(([key, value]) =>
        `<button data-strategy="${{key}}" class="${{key === activeStrategy ? 'active' : ''}}">${{value.label}}</button>`
      ).join('');
      document.querySelectorAll('[data-strategy]').forEach(button => {{
        button.addEventListener('click', () => {{
          activeStrategy = button.dataset.strategy;
          render();
        }});
      }});

      document.getElementById('riskFilters').innerHTML = riskOrder.map(risk =>
        `<button data-risk="${{risk}}" class="${{risk === activeRisk ? 'active' : ''}}">${{risk}}</button>`
      ).join('');
      document.querySelectorAll('[data-risk]').forEach(button => {{
        button.addEventListener('click', () => {{
          activeRisk = button.dataset.risk;
          render();
        }});
      }});
      document.getElementById('search').addEventListener('input', renderRows);
    }}

    function render() {{
      const plan = report.strategies[activeStrategy];
      document.querySelectorAll('[data-strategy]').forEach(button => button.classList.toggle('active', button.dataset.strategy === activeStrategy));
      document.querySelectorAll('[data-risk]').forEach(button => button.classList.toggle('active', button.dataset.risk === activeRisk));

      document.getElementById('metrics').innerHTML = [
        ['方案', plan.label],
        ['目标志愿', plan.targetSize],
        ['实际生成', plan.recommendations.length],
        ['剔除候选', plan.rejectionsTotal],
        ['保底数量', (plan.riskCounts['保'] || 0) + (plan.riskCounts['强保'] || 0)],
      ].map(([label, value]) => `<div class="metric"><b>${{value}}</b><span>${{label}}</span></div>`).join('');

      const maxCount = Math.max(1, ...Object.values(plan.riskCounts));
      document.getElementById('riskBars').innerHTML = riskOrder.filter(r => r !== '全部').map(risk => {{
        const count = plan.riskCounts[risk] || 0;
        return `<div class="bar"><span>${{risk}}</span><div class="track"><div class="fill ${{riskClass(risk)}}" style="width:${{count / maxCount * 100}}%"></div></div><b>${{count}}</b></div>`;
      }}).join('');

      document.getElementById('warnings').innerHTML = plan.warnings.length
        ? plan.warnings.map(item => `<li>${{item}}</li>`).join('')
        : '<li>当前方案未触发结构性提醒。</li>';
      document.getElementById('quotaLine').textContent = '目标配额：' + Object.entries(plan.quotas).map(([k, v]) => `${{k}} ${{v}}`).join(' / ');
      renderRows();
    }}

    function renderRows() {{
      const plan = report.strategies[activeStrategy];
      const q = document.getElementById('search').value.trim().toLowerCase();
      const rows = plan.recommendations.filter(item => {{
        const matchesRisk = activeRisk === '全部' || item.risk_band === activeRisk;
        const matchesQuery = !q || item.option_name.toLowerCase().includes(q);
        return matchesRisk && matchesQuery;
      }});
      document.getElementById('empty').hidden = rows.length > 0;
      document.getElementById('rows').innerHTML = rows.map((item, index) => {{
        const evidence = item.evidence.map(e => `<li>${{e.year}}：最低位次 ${{fmt(e.min_rank)}}，计划 ${{fmt(e.plan_count)}}，来源 ${{e.source_id}}</li>`).join('');
        const reasons = item.reasons.map(r => `<li>${{r}}</li>`).join('');
        const warnings = item.warnings.length ? `<div class="mini">提醒：${{item.warnings.join('；')}}</div>` : '';
        const tests = item.falsification_tests.map(t => `<li>${{t}}</li>`).join('');
        const comparisons = item.comparisons.length ? `<div class="mini">可对比：${{item.comparisons.join('；')}}</div>` : '';
        return `<tr>
          <td class="rank">${{index + 1}}</td>
          <td class="option">${{item.option_name}}<div class="mini">${{item.option_key}}</div></td>
          <td class="risk"><span class="pill ${{riskClass(item.risk_band)}}">${{item.risk_band}}</span></td>
          <td class="score">参考 ${{fmt(item.weighted_reference_rank)}}<div class="mini">位次差 ${{fmt(item.rank_margin)}} · ${{item.trend}}</div></td>
          <td class="evidence">
            <ul class="evidence-list">${{reasons}}</ul>
            ${{warnings}}
            ${{comparisons}}
            <details>
              <summary>证据链和反证条件</summary>
              <ul class="evidence-list">${{evidence}}</ul>
              <div class="mini" style="margin-top:8px;">反证条件</div>
              <ul class="evidence-list">${{tests}}</ul>
            </details>
          </td>
        </tr>`;
      }}).join('');
    }}

    renderShell();
    render();
  </script>
</body>
</html>"""


if __name__ == "__main__":
    main()

