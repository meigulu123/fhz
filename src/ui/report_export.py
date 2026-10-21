"""学习报告导出：生成自包含 HTML 报告（图表内嵌，可离线打开并打印为 PDF）

零外部依赖：图表复用 plotly 已渲染的能力雷达/三档占比/成长曲线/类别雷达/ZPD
分布；首个图表以 include_plotlyjs="inline" 把 plotly.js 直接写进 HTML，其余
图表复用同一份脚本，因此导出文件不联网也能正常显示全部交互图。
"""
from __future__ import annotations

import html
import time

from src.student.diagnosis import node_confidence, proficiency
from src.ui.components import (ABILITY_DEFS, ability_figure, growth_figure,
                               mastery_share_figure, radar_figure, zpd_figure)

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 32px 40px 60px; background: #f5f7fb; color: #1e293b;
       font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; }
.wrap { max-width: 1080px; margin: 0 auto; }
.head { background: linear-gradient(120deg, #0f172a, #1e3a5f); color: #e2ecff;
        border-radius: 16px; padding: 22px 26px; }
.head h1 { margin: 0 0 6px; font-size: 24px; }
.head .meta { color: #a9c0dc; font-size: 13px; line-height: 1.7; }
h2 { font-size: 17px; margin: 30px 0 12px; padding-left: 10px;
     border-left: 4px solid #22d3ee; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
         gap: 12px; }
.card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
        padding: 12px 14px; }
.card .k { color: #64748b; font-size: 12px; }
.card .v { font-size: 20px; font-weight: 700; margin-top: 4px; color: #0f172a; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
         padding: 10px 14px; overflow: hidden; }
table { width: 100%; border-collapse: collapse; font-size: 13px; background: #fff; }
th, td { border-bottom: 1px solid #eef2f7; padding: 7px 10px; text-align: left; }
th { background: #f1f5f9; color: #475569; font-weight: 600; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; }
.green { background: #dcfce7; color: #15803d; }
.blue { background: #e0f2fe; color: #0369a1; }
.grey { background: #f1f5f9; color: #64748b; }
.note { color: #64748b; font-size: 12.5px; line-height: 1.8; }
.footer { margin-top: 34px; color: #94a3b8; font-size: 12px; text-align: center; }
.bar { position: fixed; right: 22px; bottom: 22px; }
.bar button { background: #0f172a; color: #e2ecff; border: 0; border-radius: 999px;
              padding: 11px 20px; font-size: 14px; cursor: pointer;
              box-shadow: 0 6px 18px rgba(15,23,42,.28); }
@media print { body { background: #fff; padding: 0; } .bar { display: none; }
                .head { background: #0f172a !important; -webkit-print-color-adjust: exact; } }
"""


def build_html_report(env, kg, profile, state) -> str:
    """生成学习报告的完整 HTML 文本（图表内嵌，打印/另存 PDF 友好）

    profile 为被查看学生（画像页可切换到其他学生）；state 为当前登录会话，
    仅当查看自己时才渲染依赖会话状态的六维雷达与本次诊断结论。
    """
    mem = env["mem"]
    is_self = state is not None and profile.student_id == state.student_id
    qs = mem.quiz_stats(profile.student_id)
    total_dur = mem.total_duration(profile.student_id)
    acc = qs["correct"] / qs["total"] if qs["total"] else 0.0
    prof = proficiency(acc, total_dur / qs["total"] if qs["total"] else None)
    mastered = sum(1 for t in profile.mastery.values() if t >= 0.75)
    mean = sum(profile.mastery.values()) / max(len(profile.mastery), 1)
    band = (state.report.get("band") if is_self and state.report else None) \
        or env["planner"].zpd_band(profile)

    strong = sorted((n for n, t in profile.mastery.items() if t >= 0.75),
                    key=lambda n: -profile.mastery[n])[:8]
    weak = sorted((n for n, t in profile.mastery.items() if t < 0.4),
                  key=lambda n: profile.mastery[n])[:8]

    charts = []
    if is_self:
        charts.append(("六维学习能力", ability_figure(env, state, height=380)))
    charts.append(("掌握度三档占比", mastery_share_figure(kg, profile)))
    growth = mem.mastery_growth(profile.student_id)
    if growth:
        charts.append(("成长曲线（按天）", growth_figure(growth)))
    charts.append(("七类知识掌握度雷达", radar_figure(kg, profile)))
    charts.append(("最近发展区（ZPD）分布", zpd_figure(kg, profile, band)))

    parts = [
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>{_e(profile.name or '同学')} 的学习报告</title>",
        f"<style>{_CSS}</style></head><body><div class='wrap'>",
        _head(profile, kg, mastered, band),
        "<h2>核心指标</h2>", _metric_cards(profile, kg, qs, acc, prof, total_dur,
                                          mastered, mean),
        "<h2>能力与掌握度图表</h2>",
    ]
    for i, (title, fig) in enumerate(charts):
        parts.append(f"<h3 style='font-size:14px;color:#475569;'>{_e(title)}</h3>")
        parts.append("<div class='panel'>" + fig.to_html(
            full_html=False, include_plotlyjs="inline" if i == 0 else False,
            config={"displayModeBar": False, "responsive": True}) + "</div>")
    if is_self:
        parts.append("<h2>六维能力口径</h2>")
        parts.append("<div class='note'>" + "<br>".join(
            f"· {_e(d)}：{_e(v)}" for d, v in zip(
                ["学习进度", "知识掌握", "逻辑理解", "答题正确率", "记忆巩固", "学习投入"],
                ABILITY_DEFS)) + "</div>")

    parts += [
        "<h2>知识点掌握度明细</h2>", _mastery_table(kg, profile),
        "<h2>优势与薄弱</h2>",
        f"<div class='note'><b>掌握较好</b>：{_e('、'.join(_names(kg, strong))) or '—'}<br>"
        f"<b>需要加强</b>：{_e('、'.join(_names(kg, weak))) or '—'}</div>",
    ]

    if is_self and state.report:
        r = state.report
        parts += ["<h2>本次学情诊断</h2>",
                  "<div class='note'>"
                  f"诊断覆盖 {r.get('covered', 0)} 个知识点 / "
                  f"{r.get('total_questions', 0)} 道题，"
                  f"正确率 {_e(str(r.get('accuracy', 0)))}，"
                  f"建议起点「{_e(str(r.get('suggested') or '—'))}」，"
                  f"结束原因：{_e(str(r.get('stop_reason') or '—'))}。</div>"]
        items = (state.plan or {}).get("items", [])
        if items:
            parts += ["<h2>当前学习路径</h2>", "<div class='note'>" + "<br>".join(
                f"{i}. {_e(_name(kg, it.get('node_id')))}"
                f"（{_e(it.get('tier', ''))}）" for i, it in enumerate(items, 1)) + "</div>"]
        done = _names(kg, [n for n in state.done_nodes if n in kg.nodes])
        if done:
            parts += ["<h2>本会话已完成</h2>",
                      f"<div class='note'>{_e('、'.join(done))}</div>"]

    wrongs = mem.wrong_attempts(profile.student_id)[:15]
    if wrongs:
        rows = "".join(
            f"<tr><td>{_e(_name(kg, w['node_id']))}</td>"
            f"<td>{_e((w['content'] or '').lstrip('✗ ')[:60])}</td>"
            f"<td>{time.strftime('%m-%d %H:%M', time.localtime(w['ts']))}</td></tr>"
            for w in wrongs)
        parts += ["<h2>近期错题</h2>",
                  "<table><tr><th>知识点</th><th>题目</th><th>时间</th></tr>"
                  f"{rows}</table>"]

    parts += [
        "<div class='footer'>本报告由「知途伴学」学习数据看板自动生成 · "
        f"{time.strftime('%Y-%m-%d %H:%M')} · 数据来源：本地记忆库（SQLite）</div>",
        "</div><div class='bar'><button onclick='window.print()'>🖨 打印 / 另存为 PDF</button></div>",
        "</body></html>",
    ]
    return "\n".join(parts)


def _head(profile, kg, mastered, band) -> str:
    goals = "、".join(profile.goals) if profile.goals else "暂无"
    return (
        "<div class='head'><h1>" + _e(profile.name or "同学") + " 的学习报告</h1>"
        "<div class='meta'>"
        f"专业：{_e(profile.major or '—')}　学习目标：{_e(goals)}<br>"
        f"知识图谱：{len(kg.nodes)} 个知识点　已掌握：{mastered} 个　"
        f"最近发展区：θ {band.get('z_low', '—')} ~ {band.get('z_high', '—')}"
        "</div></div>")


def _metric_cards(profile, kg, qs, acc, prof, total_dur, mastered, mean) -> str:
    cards = [
        ("已掌握知识点", f"{mastered} / {len(kg.nodes)} 个"),
        ("平均掌握度 θ", f"{mean:.3f}"),
        ("总做题数", f"{qs['total']} 题"),
        ("正确率", f"{acc * 100:.0f}%"),
        ("熟练度", f"{prof * 100:.0f}%"),
        ("累计学习时长", _fmt_duration(total_dur)),
    ]
    return "<div class='cards'>" + "".join(
        f"<div class='card'><div class='k'>{_e(k)}</div>"
        f"<div class='v'>{_e(v)}</div></div>" for k, v in cards) + "</div>"


def _mastery_table(kg, profile) -> str:
    rows = []
    for nid, node in kg.nodes.items():
        th = profile.mastery.get(nid, 0.0)
        status = "已掌握" if th >= 0.75 else ("学习中" if th > 0.05 else "未开始")
        cls = {"已掌握": "green", "学习中": "blue", "未开始": "grey"}[status]
        conf = node_confidence(profile, nid)
        rows.append((th, node.name, node.category, status, cls, conf))
    rows.sort(key=lambda r: -r[0])
    body = "".join(
        f"<tr><td>{_e(name)}</td><td>{_e(cat)}</td><td>{th:.3f}</td>"
        f"<td><span class='tag {cls}'>{status}</span></td><td>{conf}%</td></tr>"
        for th, name, cat, status, cls, conf in rows)
    return ("<table><tr><th>知识点</th><th>类别</th><th>掌握度 θ</th>"
            "<th>状态</th><th>诊断置信度</th></tr>" + body + "</table>")


def _name(kg, nid) -> str:
    return kg.nodes[nid].name if nid in kg.nodes else str(nid)


def _names(kg, nids) -> list:
    return [_name(kg, n) for n in nids]


def _fmt_duration(sec) -> str:
    h, m = divmod(int(sec) // 60, 60)
    return f"{h} 小时 {m} 分" if h else f"{m} 分钟"


def _e(text) -> str:
    return html.escape(str(text))
