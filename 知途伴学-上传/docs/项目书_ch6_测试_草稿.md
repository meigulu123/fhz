> 草稿，待插入截图与统稿（生成于 2026-09-12）。本机实际执行 `python -m pytest tests/ -q` 输出为 **56 passed, 1 warning in 4.66s**；本章所有用例的"预期结果"均摘自测试代码中的真实断言，不另作演绎。

# 第六章 系统测试

本章回答一个朴素的问题：**系统宣称的每一项能力，凭什么可信？** 知途伴学的做法是把"教育学正确性"翻译成一条条可自动执行的断言——知识图谱有没有环、掌握度更新是否符合公式、路径推荐是否落在最近发展区内、脚手架是否只引导不代答、记忆是否真的跨会话延续——全部用测试代码验证，而非口头描述。全章共 **56 个自动化用例**，按 P1（知识图谱/掌握度/路径规划）→ P2（学情诊断）→ P3（脚手架/记忆）→ P4（端到端/UI）四级优先级分层设计与执行，**全部离线运行、零外部服务依赖、一条命令可复现**。

## 6.1 测试策略与环境

### 6.1.1 三层测试金字塔

| 层级 | 覆盖内容 | 用例数 | 对应文件 |
| --- | --- | --- | --- |
| 单元测试层 | 知识图谱、掌握度模型、路径规划、学情诊断、脚手架干预、记忆反思、工具函数（7 个模块） | 50 | test_kg / test_mastery / test_planner / test_diagnosis / test_scaffold / test_memory / test_e2e_mock（工具函数部分） |
| 集成与端到端层 | MockLLM 离线模式下"注册→诊断→测验→教学→干预→反思→续学"完整 8 幕剧本，及变式重规划、状态序列化往返两个分支 | 3 | test_e2e_mock |
| UI 冒烟层 | Streamlit AppTest 无头运行：主流程、状态持久化探针、四业务页面渲染 | 3 | test_app_ui |

设计原则有三条：其一，**每个用例的预期结果必须对应测试代码中的一条真实断言**，断言即规格；其二，**依赖最小化**——LLM 层全部由 MockLLM 离线桩接管，数据库全部落在 pytest 临时目录，测试之间互不污染；其三，**可复现**——任何评审者克隆仓库后执行 `python -m pytest tests/` 一条命令即可在无网环境得到同一结果。

### 6.1.2 测试环境

**表 6.1 测试环境配置**

| 项目 | 配置 / 说明 |
| --- | --- |
| 操作系统 | Windows 11 |
| 运行环境 | Python 3.12 |
| 测试框架 | pytest（requirements.txt 声明 ≥8.0），`python -m pytest tests/ -q` 一条命令执行 |
| UI 测试 | Streamlit AppTest（streamlit.testing.v1）无头运行，不依赖浏览器与显示器 |
| LLM 层 | MockLLM 离线桩（src/llm/mock.py），全程无网络、无 API Key |
| 数据隔离 | SQLite 临时库：单元与端到端用例经 pytest tmp_path 每用例独立建库；UI 用例通过 GUOCHUANG_DB 环境变量指向临时目录，测试结束即销毁 |
| 被测数据 | 50 节点知识图谱（data/kg/ml_kg.json，真实数据）+ 150 题题库（data/kg/questions.json，每题含解析、L0~L3 四级提示与变式题）；诊断与端到端用例使用"每节点 3 题"的合成题库，不依赖数据生成任务，保证用例自身确定性 |

需要说明的是，56 个用例在设计与执行上均**不依赖任何外部服务**：无网络请求、无 API 调用、无第三方数据库，运行环境与本机演示环境完全一致。这一特性同时支撑了 6.6 节的离线可用性验证——测试与断网演练共用同一套 Mock 离线运行方式。

## 6.2 单元测试用例表

以下 7 张表列出单元测试层的全部 50 个用例。"实际结果"列依据本机 pytest 全量执行结果（56 passed）统一填写；"结论"列统一为"通过"。用例编号规则：T-模块缩写-序号（KG 知识图谱、MA 掌握度模型、PL 路径规划、DI 学情诊断、SC 脚手架干预、ME 记忆反思、UT 工具函数）。

**表 6.2-1 知识图谱模块（tests/test_kg.py，5 例）**

| 编号 | 用例名称 | 输入 / 前置 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| T-KG-01 | test_50_nodes_7_categories | 加载 data/kg/ml_kg.json | 节点总数恰为 50；7 个分类名称与数量完全匹配（数学基础 8、ML概论 4、经典监督学习 12、集成学习 5、神经网络深度学习 12、评估调优 6、无监督学习 3） | 与预期一致 | 通过 |
| T-KG-02 | test_acyclic_topological_layers | 对全图执行 Kahn 拓扑分层 | 分层覆盖全部 50 个节点；无先修节点 m01、m03、m04 位于第 0 层；每条先修边的终点层数严格大于起点层数（先修图无环，学习顺序成立） | 与预期一致 | 通过 |
| T-KG-03 | test_prereq_queries | 查询先修与后继关系 | s02∈s03 先修（线性回归→逻辑回归）、m02∈s02 先修（矩阵→线性回归）、e03∈e04 先修（GBDT 链 e01→e03→e04）；m01 无先修（空表）；s03 为 s02 后继、d02 为 d01 后继 | 与预期一致 | 通过 |
| T-KG-04 | test_related_edges_exist_and_do_not_affect_topo | 检查 related 关联边与图结构完整性 | related 边存在；related 边不参与先修约束、可出现在任意层（不影响拓扑分层）；先修边数＋关联边数＝总边数（图结构完整） | 与预期一致 | 通过 |
| T-KG-05 | test_lecture_fields_present | 遍历全部 50 个节点 | 每个节点的 lecture 字段为字符串，且 summary、keywords、objectives 均非空（讲义占位字段齐备） | 与预期一致 | 通过 |

**表 6.2-2 掌握度模型模块（tests/test_mastery.py，10 例）**

| 编号 | 用例名称 | 输入 / 前置 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| T-MA-01 | test_init_bounds | 新学生初始化掌握度 | 全部节点掌握度 θ∈[0.05, 0.85]，无越界 | 与预期一致 | 通过 |
| T-MA-02 | test_init_prior_effect | 强先验（m01/m04/b01=1.0）与无先验两画像对比 | 强先验者的 b01、s02 初始掌握度更高（先验越高、先修越强，起点越高） | 与预期一致 | 通过 |
| T-MA-03 | test_init_prereq_penalty | m01=0.0（先修崩塌）与 m01=1.0 两画像对比 | 先修未达标者的 b01 初始掌握度更低（−0.15 惩罚项生效） | 与预期一致 | 通过 |
| T-MA-04 | test_update_monotone_increase | 对 s02 连续 8 次答对（kind=quiz） | 每次更新后 θ 单调不减且 ∈[0.01, 0.99]；8 次后 s02 掌握度＞0.72（0.625 起步收敛至约 0.76） | 与预期一致 | 通过 |
| T-MA-05 | test_update_learning_rate_decays | 同一节点第 1 次与第 4 次答对更新的幅度对比 | 第 4 次更新幅度的绝对值小于第 1 次（Elo 自适应学习率随证据量衰减，越学越稳） | 与预期一致 | 通过 |
| T-MA-06 | test_update_wrong_decreases | s02 先验 1.0 后答错一次 | 答错后 θ 严格下降（答错即时修正高估） | 与预期一致 | 通过 |
| T-MA-07 | test_forgetting_decay | 对 s02 应用 30 天遗忘衰减 | θ 下降，且降幅精确符合指数衰减 exp(−0.02×30)=0.5488（误差＜0.01） | 与预期一致 | 通过 |
| T-MA-08 | test_propagation_correct_successor | 答对 s02 | 后继 s03 掌握度精确 +0.05（封顶 0.99），先修掌握带动后继提升 | 与预期一致 | 通过 |
| T-MA-09 | test_propagation_wrong_prereq | 答错 s03 | 先修 s02 掌握度精确 −0.03（保底 0.01）；s02 或 b02 进入 needs_review 待复习集 | 与预期一致 | 通过 |
| T-MA-10 | test_dialog_soft_evidence_smaller_step | 同一答对事件分别以 quiz 硬证据与 dialog 软证据更新两个同初始画像 | 对话软证据（c=1）带来的掌握度变化小于测验硬证据（对话只作小幅修正） | 与预期一致 | 通过 |

**表 6.2-3 路径规划模块（tests/test_planner.py，9 例）**

| 编号 | 用例名称 | 输入 / 前置 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| T-PL-01 | test_zpd_band_uniform | 均匀掌握度 0.3 计算 ZPD 带 | z_low=0.3、z_high=0.45（σ=0 时带下限等于掌握度均值） | 与预期一致 | 通过 |
| T-PL-02 | test_zpd_band_high_mastery_capped | 均匀掌握度 0.9 | z_high ≤ 0.95（上限封顶，不为高掌握度学生排过难内容） | 与预期一致 | 通过 |
| T-PL-03 | test_frontier_all_mastered_empty | 均匀掌握度 0.8 计算前沿集 | 前沿集为空（全部知识点均已达标，无可学节点） | 与预期一致 | 通过 |
| T-PL-04 | test_frontier_gate | 均匀掌握度 0.3 计算前沿集 | 仅无先修节点 {m01, m03, m04} 进入前沿集（先修未达标者被挡在门外） | 与预期一致 | 通过 |
| T-PL-05 | test_frontier_prereq_gate_release | m01、m04 提升至 0.7 | m02、b01、m05 进入前沿集（先修达标后后继节点即时释放） | 与预期一致 | 通过 |
| T-PL-06 | test_plan_tiers_within_band | θ=0.3，batch=10 生成路径 | 路径非空；条目按 score 降序排列；A 档节点难度均落在 [z_low, z_high] 带内 | 与预期一致 | 通过 |
| T-PL-07 | test_plan_skips_too_hard | θ=0.15，batch=50 生成路径 | 所有排入条目难度 ≤ z_high（高于 ZPD 带的节点一律不排入） | 与预期一致 | 通过 |
| T-PL-08 | test_replan_rules_stuck_l3 | θ=0.4，信号 stuck_l3，当前节点 s03 | 返回 action=review_prereq，回退节点为 s03 的某一先修（回薄弱先修重学） | 与预期一致 | 通过 |
| T-PL-09 | test_pace_params | 三组节奏参数计算 | 能力 1.0/错 0 次→pace≈0.74、batch=2；能力 0.4/错 2 次→pace=0.4（下限裁剪）、batch=1；极端错次输入→pace=1.6（上限封顶） | 与预期一致 | 通过 |

**表 6.2-4 学情诊断模块（tests/test_diagnosis.py，5 例）**

| 编号 | 用例名称 | 输入 / 前置 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| T-DI-01 | test_navigation_correct_moves_up_chain | 合成题库（主链 8 节点×3 题），从 b01 起连续答对 | 当前节点沿主链上跳：b01→s02→s03（答对即向更难知识点推进） | 与预期一致 | 通过 |
| T-DI-02 | test_navigation_wrong_drills_prereq | 在 s03 答错 | 下钻至 s03 的某一先修节点，且排除已覆盖的 s02（实际钻至 b02） | 与预期一致 | 通过 |
| T-DI-03 | test_terminates_by_question_limit | 对错交替模式持续答题（上限 30 题防护） | 必终止（finished=True）；终止原因 ∈ {达到题量上限, 已覆盖足够知识点, 水平边界震荡诊断收敛, 题库耗尽}；题量 ≤ 12+3 | 与预期一致 | 通过 |
| T-DI-04 | test_no_repeat_questions | 连续作答 6 题 | 题目 id 无重复（同一题不二次出现） | 与预期一致 | 通过 |
| T-DI-05 | test_report_builder | 答 1 对 1 错后终止并生成诊断报告 | 报告含 weak/strong/band/suggested/accuracy 字段；total_questions=2；accuracy=0.5 | 与预期一致 | 通过 |

**表 6.2-5 脚手架干预模块（tests/test_scaffold.py，10 例）**

| 编号 | 用例名称 | 输入 / 前置 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| T-SC-01 | test_detect_stuck_confusion | 意图为 confusion | 判定卡住（触发干预） | 与预期一致 | 通过 |
| T-SC-02 | test_detect_stuck_confusion_words | 回复文本含「不会/卡住了/帮帮我/太难了」 | 任一困惑词出现即判定卡住 | 与预期一致 | 通过 |
| T-SC-03 | test_detect_stuck_wrong_streak | 连错 2 次（wrong_streak=2） | 判定卡住 | 与预期一致 | 通过 |
| T-SC-04 | test_detect_stuck_recent_accuracy | 近 3 题记录为 [错,错,错] 与 [对,错,对] | 全错判定卡住；对错交替不判定（避免误干预） | 与预期一致 | 通过 |
| T-SC-05 | test_detect_stuck_help_streak | 连续求助 2 次（help_streak=2） | 判定卡住 | 与预期一致 | 通过 |
| T-SC-06 | test_detect_stuck_clean | 正常回应「我知道了，继续吧」 | 不判定卡住（正常推进不打扰） | 与预期一致 | 通过 |
| T-SC-07 | test_escalation_ladder_to_replan | engage 介入后连续答错 | 依次升级 L0（含 h0、进入 active）→L1（h1）→L2（h2）→L3（h3）；L3 仍错输出 replan=True 重规划信号 | 与预期一致 | 通过 |
| T-SC-08 | test_help_escalates | engage 后学生主动求助一次 | 升级至 L1，help_streak=1 | 与预期一致 | 通过 |
| T-SC-09 | test_escalate_without_engage_is_silent | 未 engage 直接触发 on_wrong | 返回 {L0, text=None, replan=False}，静默不干扰 | 与预期一致 | 通过 |
| T-SC-10 | test_on_correct_records_hint_profile_and_resets | 升级到 L2 后答对 | hint_profile[b01]=2 记录实际提示层级；active=False、level=0、wrong_streak=0 全部复位 | 与预期一致 | 通过 |

**表 6.2-6 记忆反思模块（tests/test_memory.py，9 例）**

| 编号 | 用例名称 | 输入 / 前置 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| T-ME-01 | test_student_roundtrip | 保存学生→读回→掌握度快照→同 id 再次保存 | name/student_id 一致；快照恢复 b01=0.72、evidence_count=4；同 id 再保存走 upsert 且名字更新为「小明2」 | 与预期一致 | 通过 |
| T-ME-02 | test_session_lifecycle | 开会话、记 2 条交互、结束会话 | interaction_count=2；结束后 recent_interactions 最新一条 content=「答对了」 | 与预期一致 | 通过 |
| T-ME-03 | test_retrieve_keyword_relevance | 3 条交互（s02 相关、d08 相关、无关闲聊），检索「线性回归损失函数」 | 返回 ≥2 条；前 2 名含 s02 且第 1 名为 s02（关键词命中优先于无关内容） | 与预期一致 | 通过 |
| T-ME-04 | test_retrieve_recency_boost | 同内容两条交互：30 天前与当前各一条 | 同样命中时新的（id 更大）排前（时间近因加权生效） | 与预期一致 | 通过 |
| T-ME-05 | test_reflect_on_session_end | 会话结束触发反思（MockLLM） | 返回反思并含 progress_summary/effective_strategies/plan_adjustments/next_session_preview 四字段；last_reflection 落库内容与返回值一致 | 与预期一致 | 通过 |
| T-ME-06 | test_reflect_periodic_every_20 | 周期触发的第 3、19、20 次交互 | 第 3、19 次不触发（None）；第 20 次触发（每 20 条交互反思一次） | 与预期一致 | 通过 |
| T-ME-07 | test_reflect_no_trigger | teach 教学事件 | 不触发反思（None） | 与预期一致 | 通过 |
| T-ME-08 | test_reflect_failure_does_not_raise | LLM 抛 RuntimeError（模拟大模型故障） | maybe_reflect 返回 None、不抛异常（反思失败不中断主流程） | 与预期一致 | 通过 |
| T-ME-09 | test_plan_and_hint_logs | 保存学习计划与一条 L1 提示记录 | hint_usage 表中该生记录数=1（计划与提示用量均可落库追踪） | 与预期一致 | 通过 |

**表 6.2-7 工具函数模块（tests/test_e2e_mock.py，2 例）**

| 编号 | 用例名称 | 输入 / 前置 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| T-UT-01 | test_choice_extraction | 解析学生回复中的选项 | 「B」→B；「我想选 C」→C；confusion 且无选项→None；intent=answer 且带 choice=D→D（选项提取稳健） | 与预期一致 | 通过 |
| T-UT-02 | test_parse_prior | 解析学生先修基础自述 | 「学过线性代数和概率统计」→{m01,m02,m04,m05}=1.0；「没学过，零基础」→{}；「高等数学学过一点」→{m03}=0.5（先验自动写入画像） | 与预期一致 | 通过 |

## 6.3 端到端 8 幕剧本测试

端到端用例 test_full_script_8_scenes 在 MockLLM 离线模式下，以一次完整会话把系统全部核心能力串成一条不间断的"8 幕剧本"：**注册开场 → 4 问对话诊断 → 自适应测验 → 讲义教学 → 巩固题答错进 L0 → 连错升级 L1→L2→L3 → 变式检验 → 变式答对完成 → 结束会话反思 → 说「继续」验证记忆开场白**。剧本全程只通过 Orchestrator 的消息接口驱动，与真实用户在 UI 上的操作一一对应；每一幕都有明确的断言验证点，任何一幕失败即整条链路红灯。同一文件中另有"变式仍错触发重规划"与"状态序列化往返"两个分支用例，一并列入下表。

**表 6.3 端到端 8 幕剧本与分支用例（tests/test_e2e_mock.py，3 例）**

| 编号 | 幕名 | 关键动作 | 验证点（真实断言） | 结论 |
| --- | --- | --- | --- | --- |
| T-E2E-01 | 幕1 注册开场 | start_session 发起会话 | 开场白含「知途」与「怎么称呼」（开场白直接带出第一问）；进入 DIAGNOSING 诊断态 | 通过 |
| T-E2E-02 | 幕2 四问对话诊断 | 依次回答姓名/专业/基础/目标 | 回复含学生名「小明」；专业写入画像；「学过线性代数和概率统计」→prior 中 m01、m04=1.0；第 4 问后进入 QUIZZING、当前题非空、目标含「深度学习」、session_id 已分配 | 通过 |
| T-E2E-03 | 幕3 自适应测验 | 对错交替作答直至收敛 | 20 轮内收敛进入 TEACHING；plan.items 与 current_node 非空；report.total_questions＞0 | 通过 |
| T-E2E-04 | 幕4 讲义教学 | 注入两段式讲义，回应 [ASK:] 提问推进分段，随后出巩固题 | 回应后回复含「第二段」且讲义推进至第 2 段（lecture_para=1）；再次回应后出现当前节点的巩固题 | 通过 |
| T-E2E-05 | 幕5 巩固题答错进 L0 | 巩固题故意答错 | 进入 INTERVENING 干预态；脚手架 level=L0；回复含 h0 引导 | 通过 |
| T-E2E-06 | 幕6 连错升级 L1→L2→L3 | 连续答错 | 依次出现 h1（level1）、h2（level2）、h3（level3）；第 4 次错（L3 仍错）触发变式题：回复含「换个形式」、variant_tried=True、当前题 stem=「变式」 | 通过 |
| T-E2E-07 | 幕7 变式答对退出 | 变式题答对（变式答案 B） | 脚手架关闭（active=False）；当前节点进入 done_nodes；回到 TEACHING 继续教学 | 通过 |
| T-E2E-08 | 幕8 结束会话反思＋记忆开场白 | 说「结束」，再说「继续」 | 「结束」后进入 REFLECTING 且 last_reflection 落库非空；「继续」后回到 TEACHING、回复含「欢迎回来」（记忆开场白）、session_id 已更换（新会话延续） | 通过 |
| T-E2E-09 | 分支：变式仍错触发重规划 | 连错 4 次至 L3 → L3 错出变式 → 变式再答错 | 回到 TEACHING、脚手架关闭；current_node 回退至原节点先修（无先修则保持原节点）；reflections 表 stuck_l3 触发记录 ≥1 条 | 通过 |
| T-E2E-10 | 分支：状态序列化往返 | 完成诊断并答一题后 to_dict→from_dict 恢复 | 画像（姓名/掌握度/待复习集）、测验状态（当前节点/已覆盖）、used_qids、history 全部一致；恢复后继续答题不崩溃且 phase 一致 | 通过 |

## 6.4 UI 无头冒烟测试

UI 层采用 Streamlit 官方测试组件 AppTest（streamlit.testing.v1）无头运行 app.py 与四个业务页面，不依赖浏览器与显示器；会话数据经 GUOCHUANG_DB 环境变量隔离到临时库。三项用例覆盖"能打开、能走通、状态不丢"三个层次。

**表 6.4 UI 无头冒烟用例（tests/test_app_ui.py，3 例）**

| 编号 | 用例名称 | 关键操作 | 验证点（真实断言） | 结论 |
| --- | --- | --- | --- | --- |
| T-UI-01 | test_login_and_diagnosis_and_quiz（完整主流程） | 无头加载 app.py：sidebar 登录 → 4 问对话诊断 → 对错交替测验 | 全程无异常；开场含「知途」「怎么称呼」；4 问后 agent_state 非空且 phase=quizzing、页面出现「题目」；≤20 轮收敛至 teaching、plan.items 与 current_node 非空、total_questions＞0 | 通过 |
| T-UI-02 | test_probe_page_buttons（状态持久化探针） | 打开探针页：点击修改按钮后 rerun；点击「一致性检查」 | 页面含「状态持久化探针」；rerun 后 probe_marker 递增且提示「rerun 后修改存活」；一致性检查后 probe_roundtrip=True 且提示「序列化往返一致」 | 通过 |
| T-UI-03 | test_business_pages_render（四页面渲染） | 以完成诊断/测验的会话状态渲染四个业务页面 | 学生画像、学习路径、知识图谱、对话学习四页均无异常，且各自标题关键词存在 | 通过 |

**"状态持久化探针"的工程意义**：Streamlit 的每一次交互都会自上而下重新执行整份脚本（rerun），这意味着会话状态必须完整驻留在 session_state 中才能跨交互存活；同时 AgentState 必须能通过 to_dict/from_dict 序列化往返，页面刷新与恢复时才不会丢状态。探针页把这两件事固化为两项可点击的门禁断言——"rerun 后状态存活"与"序列化往返一致"（对应 probe_page.py 页首的门禁说明）。任何一次重构若破坏了状态驻留或序列化能力，探针页与 T-UI-02 会立刻失败。这是智能体"跨会话续学"承诺在工程上的底线保障。

## 6.5 测试结果汇总

**表 6.5 测试用例统计**

| 测试模块 | 对应测试文件 | 用例数 | 通过 | 失败 |
| --- | --- | --- | --- | --- |
| 知识图谱 | tests/test_kg.py | 5 | 5 | 0 |
| 掌握度模型 | tests/test_mastery.py | 10 | 10 | 0 |
| 路径规划 | tests/test_planner.py | 9 | 9 | 0 |
| 学情诊断 | tests/test_diagnosis.py | 5 | 5 | 0 |
| 脚手架干预 | tests/test_scaffold.py | 10 | 10 | 0 |
| 记忆反思 | tests/test_memory.py | 9 | 9 | 0 |
| 工具函数 | tests/test_e2e_mock.py（2 例） | 2 | 2 | 0 |
| 端到端集成 | tests/test_e2e_mock.py（3 例） | 3 | 3 | 0 |
| UI 冒烟 | tests/test_app_ui.py | 3 | 3 | 0 |
| **合计** | — | **56** | **56** | **0** |

本机实际执行 `python -m pytest tests/ -q` 的关键输出如下（2026-09-12 实测，全离线）：

```
$ python -m pytest tests/ -q
........................................................                 [100%]
============================== warnings summary ===============================
C:\...\Python312\Lib\site-packages\jieba\_compat.py:18: UserWarning:
  pkg_resources is deprecated as an API. ... Refrain from using this
  package or pin to Setuptools<81.
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
56 passed, 1 warning in 4.66s
```

关于唯一一条 warning：它来自第三方分词库 jieba 自身对 pkg_resources 的弃用提示（Python 3.12 环境下 setuptools 的 API 弃用预告），与本项目代码无关；经确认对全部功能与测试结果无任何影响，测试环境已确认，不影响交付。

📷【截图位置 S06-1】终端执行 `pytest tests/` 全绿输出截图（建议宽 1000px 起）

## 6.6 离线可用性验证（断网演练）

56 个用例在设计上已全部离线（MockLLM、无外部服务），但"代码层离线"不等于"整机断网可演示"，因此设置一次专项断网演练，在运行层面复核系统对网络与 API Key 的零依赖承诺。

**验证方法**：① 准备——在测试机上禁用网卡（或拔除网线），确认无任何代理与本地大模型服务进程；② 启动——不配置任何 API Key，执行 `streamlit run app.py`，确认应用正常启动、由 MockLLM 离线接管；③ 演练——完整走一遍 6.3 节 8 幕剧本（注册 → 4 问诊断 → 自适应测验 → 讲义 → L0→L3 脚手架 → 变式 → 反思 → 记忆开场白）；④ 复核——逐项勾选下方验收清单并截图存档。

**表 6.6 断网演练验收清单**

| 序号 | 验收项 | 验收标准 |
| --- | --- | --- |
| 1 | 断网启动 | `streamlit run app.py` 正常启动，无网络请求报错、无 API Key 报错 |
| 2 | 对话诊断 | 4 问对话诊断完整走通，先验基础与学习目标正确写入画像 |
| 3 | 测验与路径 | 自适应测验收敛，生成可解释的学习路径并正常渲染 |
| 4 | 脚手架与记忆 | L0→L3 升级、变式检验、重规划全部可用；反思落库、跨会话记忆开场白正常 |
| 5 | 数据本地化 | SQLite 读写全部在本机完成，无任何数据流出本机 |

**离线演练结论：待执行（9.14 演练，届时替换本段结论）。**

📷【截图位置 S06-2】断网演练运行画面截图（建议宽 1000px 起）
