"""Demo 数据组装与三项校验（P0 验证门）

① KG 先修图无环（KnowledgeGraph 加载即校验）
② 题目 node_id 与图谱节点 ID 双向对齐：题库不引用不存在节点；每个节点 ≥2 题
③ 讲义合法：每个节点讲义非空且 [ASK:] 提问位 ≥2

流程：读 ml_kg.json + gen_{A,B,C,D}.json（讲义）→ 注入 lecture →
     合并 gen_q_{A,B,C,D}.json → 写 questions.json → 跑三项校验。
用法：python scripts/build_demo_data.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

KG_PATH = ROOT / "data" / "kg" / "ml_kg.json"
Q_PATH = ROOT / "data" / "kg" / "questions.json"
GEN_FILES = ["gen_A.json", "gen_B.json", "gen_C.json", "gen_D.json"]
QGEN_FILES = ["gen_q_A.json", "gen_q_B.json", "gen_q_C.json", "gen_q_D.json"]

failures = []


def fail(msg):
    failures.append(msg)
    print(f"  [FAIL] {msg}")


def ok(msg):
    print(f"  [OK]   {msg}")


def main():
    print("== 1. 合并讲义 ==")
    kg = json.loads(KG_PATH.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in kg["nodes"]}
    for fname in GEN_FILES:
        path = ROOT / "data" / "kg" / fname
        if not path.exists():
            fail(f"缺少讲义文件 {fname}（对应数据生成任务尚未完成？）")
            continue
        gen = json.loads(path.read_text(encoding="utf-8"))
        for item in gen.get("nodes", []):
            nid = item["id"]
            if nid not in nodes:
                fail(f"讲义引用了不存在的节点 {nid}")
                continue
            if not item.get("lecture"):
                fail(f"节点 {nid} 讲义为空")
                continue
            nodes[nid]["lecture"] = item["lecture"]
        ok(f"{fname}: 合并 {len(gen.get('nodes', []))} 份讲义")
    KG_PATH.write_text(json.dumps(kg, ensure_ascii=False, indent=2), encoding="utf-8")

    print("== 2. 合并题库 ==")
    all_qs = []
    for fname in QGEN_FILES:
        path = ROOT / "data" / "kg" / fname
        if not path.exists():
            fail(f"缺少题库文件 {fname}（对应数据生成任务尚未完成？）")
            continue
        gen = json.loads(path.read_text(encoding="utf-8"))
        all_qs.extend(gen.get("questions", []))
        ok(f"{fname}: 合并 {len(gen.get('questions', []))} 题")
    Q_PATH.write_text(json.dumps({"questions": all_qs}, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    print("== 3. 校验 ==")
    from src.kg.loader import KnowledgeGraph
    kg_obj = KnowledgeGraph.load(str(KG_PATH))
    if len(kg_obj.nodes) == 50:
        ok("① KG 先修图无环，50 节点加载成功")
    else:
        fail(f"① 节点数 {len(kg_obj.nodes)} ≠ 50")

    # ② 双向对齐
    q_by_node = {}
    for q in all_qs:
        nid = q["node_id"]
        if nid not in kg_obj.nodes:
            fail(f"② 题目 {q['id']} 引用不存在的节点 {nid}")
        q_by_node.setdefault(nid, []).append(q["id"])
    missing = [nid for nid in kg_obj.nodes if len(q_by_node.get(nid, [])) < 2]
    if missing:
        fail(f"② 以下节点题目数 <2：{missing}")
    else:
        ok(f"② 双向对齐通过：{len(all_qs)} 题，50 节点每节点 ≥2 题")

    # ③ 讲义 [ASK:]
    bad_lecture = [nid for nid, n in kg_obj.nodes.items()
                   if not n.lecture or n.lecture.count("[ASK:]") < 2]
    if bad_lecture:
        fail(f"③ 以下节点讲义缺失或 [ASK:] <2：{bad_lecture}")
    else:
        ok("③ 讲义合法：全部节点讲义非空且 [ASK:] ≥2")

    # 题目字段完整性抽查（全部检查）
    bad_q = []
    for q in all_qs:
        opts = q.get("options", [])
        if q.get("answer") not in [o[:1] for o in opts if o]:
            bad_q.append(q["id"])
        for lv in ("L0", "L1", "L2", "L3"):
            if not q.get("hints", {}).get(lv):
                bad_q.append(f"{q['id']}(缺{lv})")
        if not q.get("variant", {}).get("stem"):
            bad_q.append(f"{q['id']}(缺变式题)")
    if bad_q:
        fail(f"题目字段不完整：{bad_q[:10]}")
    else:
        ok(f"题目字段完整：answer 合法、L0~L3 齐全、变式题齐全")

    print()
    if failures:
        print(f"校验未通过：{len(failures)} 项失败")
        sys.exit(1)
    print(f"校验全部通过：50 节点 / {len(all_qs)} 题，可以进入 P1。")


if __name__ == "__main__":
    main()
