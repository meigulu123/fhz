"""反思：会话结束/节点完成/卡死 L3/每 20 次交互 触发

输出 progress_summary / effective_strategies / plan_adjustments /
next_session_preview；存 reflections 表；next_session_preview 用于
新会话开场白（跨会话记忆延续，演示第 8 幕）。
"""
from __future__ import annotations

from .retrieve import stats_json


def maybe_reflect(mem, llm, kg, profile, session_id, trigger,
                  interaction_count=0, report=None, done_nodes=None) -> dict | None:
    """按触发条件决定是否反思；返回反思 dict 或 None"""
    periodic = trigger == "periodic" and interaction_count % 20 == 0
    if trigger not in ("session_end", "node_done", "stuck_l3") and not periodic:
        return None
    stats = stats_json(profile, kg, report=report, done_nodes=done_nodes)
    messages = [
        {"role": "system",
         "content": ("[TPL:reflection]\n你是学习反思助手。基于以下学情统计，输出 JSON："
                     "progress_summary/effective_strategies/plan_adjustments/"
                     "next_session_preview 四个字段（均为字符串）。")},
        {"role": "user",
         "content": f"[trigger={trigger}][stats_json={_json(stats)}]"},
    ]
    try:
        content = llm.chat_json(messages)
    except Exception:  # noqa: BLE001 —— 反思失败不阻断教学主流程
        return None
    mem.save_reflection(session_id, profile.student_id, trigger, content)
    return content


def _json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)
