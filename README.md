
# 知途伴学 · 本地 API Key（此文件已加入 .gitignore，不会随作品提交）
LLM_API_KEY=ak-6235321da7716f2c73cca42a18b4ac70

# Python 缓存
__pycache__/
*.pyc
*.pyo

# 本地数据库（含账号密码哈希与学习记录，绝不上传）
data/zhitu.db
data/zhitu.db-wal
data/zhitu.db-shm

# API Key 等敏感配置
.env
.streamlit/secrets.toml

# 与本项目无关的文件（其他项目的参考资料）
智医慧眼-商业计划书 (1).pdf
.ref_text.txt

# 本机专属配置
.claude/settings.local.json

"""知途伴学 · Streamlit 入口（登录页 → 核心界面五页导航）

未登录只渲染登录页；登录后进入核心界面：对话学习 / 学生画像 / 学习路径 /
知识图谱 / 状态探针。无任何 API Key 时 MockLLM 离线兜底，配置真实 Key 后
自动切换真实大模型。
"""
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.agent.state import AgentState  # noqa: E402
from src.ui.env import build_env  # noqa: E402
from src.ui.pages.account_page import account_page  # noqa: E402
from src.ui.pages.chat_page import chat_page  # noqa: E402
from src.ui.pages.home_page import home_page  # noqa: E402
from src.ui.pages.kg_page import kg_page  # noqa: E402
from src.ui.pages.login_page import login_page  # noqa: E402
from src.ui.pages.path_page import path_page  # noqa: E402
from src.ui.pages.profile_page import profile_page  # noqa: E402
from src.ui.probe_page import probe_page  # noqa: E402

st.set_page_config(page_title="知途伴学",
                   page_icon=str(ROOT / "assets" / "logo.png"), layout="wide")

from src.ui.theme import inject_theme, logo_html  # noqa: E402

inject_theme()


@st.cache_resource
def get_env():
    return build_env()


env = get_env()
st.session_state["env"] = env
if "agent_state" not in st.session_state:
    st.session_state["agent_state"] = None

# ---------- 登录门禁：未登录只显示登录页 ----------
if st.session_state["agent_state"] is None:
    login_page(env)
    st.stop()

state = st.session_state["agent_state"]


def _top_bar(current):
    """页面顶栏：左侧返回首页（首页不显示），右上角账户入口"""
    left, right = st.columns([5, 1.4], vertical_alignment="center")
    with left:
        if current.title != "首页":
            st.markdown('<div class="back-home-bar">', unsafe_allow_html=True)
            if st.button("← 返回首页", key="back_home"):
                st.switch_page(st.Page(home_page))
            st.markdown('</div>', unsafe_allow_html=True)
    with right:
        with st.container(key="top_account"):
            if st.button(f":material/account_circle: {state.student_id}",
                         key="acct_entry", help="账户管理"):
                st.switch_page(st.Page(account_page))


# ---------- 侧边栏（登录后） ----------
with st.sidebar:
    st.markdown(f'<div style="padding:2px 0 6px 0;">{logo_html(150, "0 0 0 0")}</div>',
                unsafe_allow_html=True)
    st.divider()
    st.markdown(f"**学生**：{state.student_id}")
    if st.button("结束本次会话", use_container_width=True,
                 disabled=state.phase == "reflecting"):
        env["orch"].handle(state, "结束")
        st.rerun()
    if st.button("退出登录", use_container_width=True):
        st.session_state["agent_state"] = None
        st.session_state["login_pwd"] = ""  # 退出后清除密码框，避免残留
        st.rerun()
    st.divider()
    llm_cfg = env["cfg"]["llm"]
    mode = ("真实大模型：" + llm_cfg.get("model", "")) \
        if llm_cfg.get("provider") != "mock" else "离线模式（未配置 Key）"
    st.caption(mode)
    st.caption(f"知识库：{len(env['kg'].nodes)} 节点 / {len(env['questions'])} 题")

# ---------- 核心界面 ----------
pages = [
    st.Page(home_page, title="首页", default=True),
    st.Page(chat_page, title="对话学习"),
    st.Page(profile_page, title="学生画像"),
    st.Page(path_page, title="学习路径"),
    st.Page(kg_page, title="知识图谱"),
    st.Page(account_page, title="账户管理"),
    st.Page(probe_page, title="状态探针"),
]
current = st.navigation(pages)
_top_bar(current)
current.run()

"""pytest 根配置：把项目根目录加入 sys.path，使 tests/ 可直接 import src.*"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# 知途伴学 · 大模型驱动的自适应学习路径决策与伴学智能体

> 中国国际大学生创新大赛（2026）产业命题赛道 · 命题九十六
> 命题企业：科大讯飞 · 团队：广东理工学院 · 知途伴学

一个**可离线运行**的自适应学习伴学智能体：以 50 节点机器学习知识图谱为骨架，通过
对话诊断 + 自适应测验构建学生画像，规划 ZPD 最近发展区学习路径，在教学中以
L0~L3 四级脚手架实时干预，并用 SQLite 记忆库支撑跨会话记忆与反思。
接入任意 OpenAI 兼容大模型（星火 / DeepSeek / Qwen / GLM）即可从 Mock 离线模式
无缝切换为真实大模型模式——**两者接口契约完全相同**。

## 快速开始（零配置，无任何 API Key 即可完整运行）

> 要求 Python 3.9+（本项目已兼容 3.9）。

```bash
pip install -r requirements.txt
streamlit run app.py
```

浏览器打开 http://localhost:8501，点击左侧「🚀 登录 / 开始学习」即可体验完整流程：

1. **对话诊断**：4 问了解称呼 / 学校专业 / 数学与机器学习基础 / 学习目标
2. **自适应测验**：答对沿主链上跳、答错下钻先修，收敛后生成诊断报告
3. **学习路径**：ZPD 带 + 拓扑前沿 + 节奏参数（准确率 / 卡住次数）自动出计划
4. **伴学教学**：分段讲义推进，卡住时自动触发 L0 苏格拉底反问 → L1 概念提示
   → L2 类比样例 → L3 分步解析 + 变式检验；变式仍错则重规划回补先修
5. **会话反思**：「结束」触发反思落库，重新登录后开场白引用上次学习记忆
6. **知识问答**：随时自由提问（如「什么是反向传播」），从知识库检索知识点并即时解答

右侧信息卡实时显示相位 / 当前知识点 / 掌握度 / 讲义进度 / 脚手架层级 / 路径计划；
「📊 学生画像」「🗺️ 学习路径」「🕸️ 知识图谱」页面可视化画像与规划全貌。

## 切换真实大模型（可选）

编辑 `config/config.yaml` 或设置环境变量：

```yaml
llm:
  provider: maas           # mock（默认离线）| maas（讯飞星辰 MaaS）
  api_key: "你的Key"        # 缺省自动回退 Mock 离线模式（建议放 .env 的 LLM_API_KEY）
  base_url: https://maas-api.cn-huabei-1.xf-yun.com/v2   # 讯飞星辰 MaaS 推理服务
  model: spark-x2.5-4b     # MaaS 模型 ID，以「服务管控 > 模型服务列表」为准
```

> 当前接的是讯飞星辰 MaaS（`maas.xfyun.cn`，命题企业科大讯飞，学生可申请免费
> 额度）。任何 OpenAI 兼容服务（DeepSeek / Qwen / GLM 等）改 `base_url` + `model` 即可。
> 无 Key 时系统自动降级 Mock 离线模式，**全部功能仍 100% 可用**（断网演示无忧）。

## 架构一览

```
app.py                    Streamlit 入口（五页导航 + 侧边栏会话控制）
src/agent/                编排器 + 状态机（感知→规划→行动→记忆主循环）
src/student/              学生画像、掌握度模型、学情诊断
src/path/                 ZPD 路径规划 + 节奏参数
src/tutor/                L0~L3 脚手架干预 + 分段讲义教学
src/memory/               SQLite 记忆库（7 表）+ 检索 + 反思
src/llm/                  大模型抽象层（OpenAI 兼容 / MockLLM 离线兜底）
src/kg/                   知识图谱模型与拓扑查询
data/kg/                  50 节点知识图谱 + 150 题题库（每题含 L0~L3 hints）
config/                   配置（yaml + 环境变量 + 运行时三级合并）
tests/                    84 个 pytest 用例（全离线，覆盖模型层到 UI）
scripts/                  数据构建校验 / CLI 端到端 / 演示脚本
docs/                     商业计划书 / 技术方案文档 / 演示视频脚本
```

## 测试

```bash
pytest tests/          # 84 用例全离线：KG 校验、掌握度公式、路径规划、
                       # 诊断、脚手架、记忆反思、8 幕端到端、UI 无头冒烟
python scripts/e2e_cli.py   # 命令行完整走一遍"诊断→测验→路径→教学→干预"
python scripts/test_real_llm.py  # 配置真实 Key 后跑回归（连通性/结构化输出/8 幕剧本）；
                       # 未配置 Key 时优雅跳过，不影响离线演示
```

## 核心设计

- **掌握度模型**：`θ' = θ + K·(c − p)`，`p = sigmoid(8(θ−0.5))`，学习率随答题次数衰减；
  答对后继 +0.05 传播、答错先修 −0.03 标记复习；跨会话遗忘衰减 `exp(−0.02·Δt天)`
- **ZPD 路径**：难度带 `[mean(θ), min(mean+0.15+0.35σ, 0.95)]`，带内主修 / 带下复习 /
  带上暂缓；评分 = 0.30·ZPD + 0.25·(1−θ) + 0.20·中心性 + 0.15·目标相似度 + 0.10·认知契合
- **双通道 LLM**：每条消息同时携带结构化标记（`[TPL:][node=][para=]…`，Mock 路由键）
  与原始素材（讲义 / 题干，真实 LLM 材料），Mock 与真实模式共用同一接口契约
- **记忆延续**：会话结束反思产出 `next_session_preview`，新会话开场白自动引用
- **知识问答（RAG）**：jieba 关键词检索命中知识点（支持跨知识点对比），双通道 LLM
  结合学生画像基于讲义生成解答（Mock 走模板取真实讲义节选、真实模型走大模型，
  自由提问不打断学习状态机）

## 借鉴与改进

| 来源 | 借鉴 | 本项目改进 |
|---|---|---|
| HKUDS/DeepTutor（Apache-2.0） | 掌握度路径、三层记忆架构 | 轻量 SQLite 实现；掌握度写成显式可解释公式；路径加 ZPD 带与节奏参数 |
| d2l-ai/d2l-zh（Apache-2.0） | 由浅入深知识编排 | 讲义结构化：分段 + 内嵌 `[ASK:]` 提问位 |
| ECNU-ICALK/EduChat | 苏格拉底式引导教学 | 四级脚手架显式化 + 题库 hints 锚定防幻觉 + 变式检验闭环 |

## 文档

- [docs/商业计划书.md](docs/商业计划书.md) — 项目书（背景→设计→实现→测试→商业→展望）
- [docs/技术方案文档.md](docs/技术方案文档.md) — 六层架构 / 知识库构建 / 动态路径优化原理
- [docs/演示视频脚本.md](docs/演示视频脚本.md) — 3-5 分钟分镜

## 品牌素材

`assets/` 存放 logo 与吉祥物。原始图为白底 JPG，运行一次处理脚本生成透明 PNG：

```bash
python scripts/prepare_assets.py
```

- `logo.png` — 白底剥离后的原始 logo（浅色背景用，如项目书插图）
- `logo_light.png` / `logo_light@2x.png` — 深色界面专用变体（藏青部分提亮为浅蓝，
  青绿与橙色保持），登录页 / 首页 / 侧边栏使用
- `mascot.png` / `mascot@2x.png` — 吉祥物（保留白色脸部，用作对话页助手头像）

处理逻辑：logo 用全局白度剥离（连字符内部字腔一并处理，否则深色底上会留白块）；
吉祥物用四边洪水填充（避免把白色脸部挖空）。`tests/test_assets.py` 守住产物质量。

## 截图素材

`python scripts/screenshot_pages.py`（依赖 playwright，仅开发期工具）自动驱动
Streamlit 走完 8 幕剧本并输出各页面 PNG 到 `docs/screenshots/`，供项目书插图使用。

streamlit>=1.36
plotly>=5.22
networkx>=3.2
jieba>=0.42
pyyaml>=6.0
openai>=1.30
pytest>=8.0

