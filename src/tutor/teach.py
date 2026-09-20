"""教学：讲义分段进度控制（分段边界 = [ASK:] 提问位）

双通道设计：消息同时携带标记（[node=][para=]，Mock 路由键）与讲义原文
（真实 LLM 的教学素材）——Mock 只读标记从 KG 取原文，真实 LLM 基于原文改写讲解。
"""
from .scaffold import LEVELS  # noqa: F401 —— 保持模块间显式依赖关系清晰


def split_segments(lecture: str) -> list:
    """按 [ASK:] 提问位切分讲义为教学段；每段以提问结尾（最后一段可能无）"""
    blocks = [b.strip() for b in lecture.split("\n\n") if b.strip()]
    segs, cur = [], []
    for b in blocks:
        if b.startswith("[ASK:]"):
            segs.append(cur + [b])
            cur = []
        else:
            cur.append(b)
    if cur:
        segs.append(cur)
    return ["\n\n".join(s) for s in segs]


def segment_count(lecture: str) -> int:
    return len(split_segments(lecture)) if lecture else 0


def teach_segment(llm, node_id: str, para: int, segment_text: str = "") -> str:
    """请求 LLM 讲第 para 段：Mock 按标记从 KG 取原文；真实 LLM 用 segment_text 改写"""
    user = f"[node={node_id}][para={para}]"
    if segment_text:
        user += f"\n【讲义原文，请基于它讲解】\n{segment_text}"
    messages = [
        {"role": "system", "content": "[TPL:teach]\n你是伴学导师，按讲义分段讲解，"
                                      "语气亲切，保持知识点准确，"
                                      "不直接给出 [ASK:] 问题的答案。"},
        {"role": "user", "content": user},
    ]
    return llm.chat(messages)
