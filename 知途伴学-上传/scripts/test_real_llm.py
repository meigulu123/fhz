"""真实大模型回归：连通性 → 结构化输出 → 8 幕剧本（配置真实 Key 后运行）

用法：
    python scripts/test_real_llm.py

行为：
- 未配置真实 Key（provider=mock 或 api_key 为空）→ 打印提示并正常退出（exit 0），
  不联网、不报错——离线 Mock 模式仍可随时演示。
- 已配置 → 三组回归，全部通过 exit 0，任一失败 exit 1：

  ① 连通性     chat() 简单对话返回非空文本
  ② 结构化输出 chat_json() 意图分类返回合法 intent（与编排器同款提示词）
  ③ 8 幕剧本   与 tests/test_e2e_mock.py 同构的场景骨架，真实 LLM 在环驱动
               全流程（意图分类 / 答题反馈 / 诊断叙述 / 讲义改写 / 记忆开场白）。
               断言策略：状态机从严（相位 / 掌握度 / 落库），文本从宽（LLM 措辞自由）。

配置：与 app.py 完全一致——config/config.yaml 的 llm 段，或环境变量
      LLM_PROVIDER / LLM_API_KEY / LLM_BASE_URL / LLM_MODEL。
      脚本绝不打印 api_key。

典型用法（星火 OpenAI 兼容接口）：
    LLM_PROVIDER=spark LLM_API_KEY=xxx LLM_BASE_URL=https://spark-api-open.xf-yun.com/v1 \
    LLM_MODEL=generalv3.5 python scripts/test_real_llm.py

注意：真实模式下全剧本约 50~60 次 LLM 调用（含重试），耗时取决于供应商。
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 与 tests/test_e2e_mock.py 同构的标准两段式讲义：第二段以 [ASK:] 结尾，
# 用于确定性验证讲义分段推进（与 Mock 回归对比同构性）
LECTURE = ("第一段：损失函数衡量模型预测与真实标签之间的差异，是优化的目标。\n\n"
           "[ASK:] 为什么线性回归常用平方损失？\n\n"
           "第二段：因为平方损失可导且是凸函数，便于用梯度下降优化。")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return ok


def wrong_choice(q):
    """返回一个必然错误的选项字母（真实题库答案分布无规律）"""
    return "A" if q["answer"] != "A" else "B"


def run_smoke(llm, orch):
    """①② 连通性 + 结构化输出"""
    print("\n[1/3] 连通性：chat()")
    try:
        reply = llm.chat([{"role": "user", "content": "你好，请只回复四个字：连接成功"}])
        check("chat 返回非空文本", bool(reply and reply.strip()), repr(reply[:40]))
    except Exception as exc:  # noqa: BLE001
        check("chat 返回非空文本", False, f"异常：{exc}")

    print("\n[2/3] 结构化输出：chat_json() 意图分类（编排器同款提示词）")
    messages = [
        {"role": "system",
         "content": "[TPL:intent]\n你是伴学智能体的意图识别模块。根据学生输入输出 JSON："
                    "{\"intent\": \"answer|confusion|goal_change|question|end_session|other\","
                    " \"choice\": \"A/B/C/D（若为答题输入，否则省略）\", \"confidence\": 0~1}。"},
        {"role": "user", "content": "我想选 B"},
    ]
    try:
        intent = llm.chat_json(messages)
        valid = {"answer", "confusion", "goal_change", "question", "end_session", "other"}
        ok = isinstance(intent, dict) and intent.get("intent") in valid
        check("意图分类 JSON 合法", ok, str(intent)[:70])
        # choice 非硬契约：编排器先用正则从学生原文提取选项，choice 仅作兜底
        if ok and intent.get("intent") == "answer" and not intent.get("choice"):
            print("  [WARN] intent=answer 但 choice 缺失（不影响运行，"
                  "可留意意图提示词调优）")
    except Exception as exc:  # noqa: BLE001
        check("意图分类 JSON 合法", False, f"异常：{exc}")


def run_scenes(orch, kg, mem):
    """③ 8 幕剧本：真实 LLM 全流程驱动，状态机断言从严"""
    from src.agent.state import (AgentState, DIAGNOSING, INTERVENING,
                                 QUIZZING, REFLECTING, TEACHING)

    print("\n[3/3] 8 幕剧本：真实 LLM 全流程驱动")
    state = AgentState(student_id="real_llm_user")

    # 幕1 注册开场（问候为 LLM 生成，第一问为模板，只断言模板部分）
    reply, _ = orch.start_session(state)
    check("幕1 注册开场（问候 + 第一问）",
          "怎么称呼" in reply and state.phase == DIAGNOSING,
          reply[:44].replace("\n", " "))

    # 幕2 4 问对话诊断（规则驱动，与 Mock 回归断言一致）
    orch.handle(state, "小明")
    check("幕2-1 姓名提取", state.profile.name == "小明")
    orch.handle(state, "计算机专业")
    orch.handle(state, "学过线性代数和概率统计")
    check("幕2-2 先修解析", state.profile.prior.get("m01") == 1.0
          and state.profile.prior.get("m04") == 1.0)
    orch.handle(state, "想重点学深度学习")
    check("幕2-3 进入自适应测验",
          state.phase == QUIZZING and state.current_question is not None)

    # 幕3 自适应测验：模拟约 50% 正确率的学生（对、对、错、错成对作答）。
    # 任意 3 连窗口内至少 1 对 → 不会 0/3 触发卡住判定，避免进入教学时被
    # 「近3轮正确率<1/3」误判为卡住而跳过讲义（真实题库答案分布无规律，
    # 盲答 A/B 交替会在测验结尾出现 3 连错）。
    for i in range(40):
        if state.phase != QUIZZING:
            break
        q = state.current_question
        answer = q["answer"] if (i // 2) % 2 == 0 else wrong_choice(q)
        orch.handle(state, answer)
    if not check("幕3 测验收敛出路径",
                 state.phase == TEACHING
                 and (bool(state.current_node) or not state.plan.get("items")),
                 f"{state.report.get('total_questions', 0)}题，"
                 f"当前节点 {state.current_node or '—'}"):
        print("  路径未生成，跳过幕4-8")
        return
    cur = state.current_node

    # 幕4 教学对话：注入标准讲义 → 回应 [ASK:] 推进分段 → 出巩固题
    kg.nodes[cur].lecture = LECTURE
    reply, _ = orch.handle(state, "我觉得平方损失可导所以好优化")
    check("幕4 讲义分段推进（[ASK:]）",
          state.lecture_para == 1 and bool(reply.strip()),
          f"lecture_para={state.lecture_para}")
    state.used_qids = []
    reply, _ = orch.handle(state, "明白了，凸函数局部最优就是全局最优")
    check("幕4 出巩固题",
          state.current_question is not None
          and state.current_question.get("node_id") == cur)

    # 幕5 巩固题答错 → L0 脚手架（错项按真实答案动态计算）。
    # 注意：脚手架会换用同节点未做过的题，每次作答前都重新捕获当前题。
    reply, payload = orch.handle(state, wrong_choice(state.current_question))
    check("幕5 答错进入 L0 脚手架",
          state.phase == INTERVENING and payload["scaffold"]["level"] == "L0")

    # 幕6 连错升级 L1→L2→L3
    for lv in (1, 2, 3):
        orch.handle(state, wrong_choice(state.current_question))
        check(f"幕6 连错升级 L{lv}", state.scaffold.level == lv)

    # L3 仍错 → 变式题检验
    q = state.current_question
    reply, _ = orch.handle(state, wrong_choice(q))
    check("幕6 变式题检验",
          state.scaffold.variant_tried
          and state.current_question.get("stem") == q["variant"].get("stem"))

    # 幕7 变式答对 → 退出脚手架，节点完成
    reply, payload = orch.handle(state, state.current_question["answer"])
    check("幕7 变式答对退出脚手架",
          payload["scaffold"]["active"] is False
          and cur in state.done_nodes and state.phase == TEACHING)

    # 幕8 结束会话反思落库；「继续」→ 记忆开场白（LLM 生成，只断言非空）+ 新会话
    sid_old = state.session_id
    orch.handle(state, "结束")
    check("幕8 结束会话进入反思",
          state.phase == REFLECTING
          and mem.last_reflection("real_llm_user") is not None)
    reply, payload = orch.handle(state, "继续")
    check("幕8 记忆开场白 + 新会话",
          state.phase == TEACHING and state.session_id != sid_old
          and bool(reply.strip()))


def main():
    from src.llm.mock import MockLLM
    from src.ui.env import build_env

    env = None
    tmpdir = Path(tempfile.mkdtemp(prefix="guochuang_real_llm_"))
    try:
        env = build_env({"paths": {"db": str(tmpdir / "real.db")}})
        llm, cfg = env["llm"], env["cfg"]["llm"]

        if isinstance(llm, MockLLM):
            print("未配置真实大模型 Key（当前 provider=%s）。" % cfg.get("provider"))
            print("跳过回归——离线 Mock 模式不受影响，演示随时可用。")
            print("\n配置方式（与 app.py 一致）：编辑 config/config.yaml 的 llm 段，"
                  "或设置环境变量")
            print("  LLM_PROVIDER / LLM_API_KEY / LLM_BASE_URL / LLM_MODEL")
            print("配置后重跑：python scripts/test_real_llm.py")
            return 0

        print("检测到真实大模型：provider=%s model=%s base_url=%s"
              % (cfg.get("provider"), cfg.get("model"), cfg.get("base_url")))
        print("（注意：api_key 不会被打印；全剧本约 50~60 次调用）")

        run_smoke(llm, env["orch"])
        run_scenes(env["orch"], env["kg"], env["mem"])
    finally:
        if env is not None:
            env["mem"].close()
        shutil.rmtree(tmpdir, ignore_errors=True)

    total, passed = len(RESULTS), sum(ok for _, ok in RESULTS)
    print("\n" + "=" * 60)
    print(f"回归结束：{passed}/{total} 通过")
    for name, ok in RESULTS:
        if not ok:
            print(f"  ✗ {name}")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
