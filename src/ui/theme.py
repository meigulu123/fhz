"""全局视觉主题：深色科技风 + 玻璃拟态（Glassmorphism）+ 霓虹青蓝

设计语言：深空底色 + 全息光晕 + 半透明玻璃卡片 + 青色描边发光。
仅在页面顶部注入一次 CSS，所有页面共享；不依赖外部字体与 CDN 资源。
品牌素材：assets/logo_light.png（深色界面用 logo）、assets/mascot.png（吉祥物）。
"""
import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
LOGO_LIGHT = ROOT / "assets" / "logo_light@2x.png"   # 预缩放 2 倍，展示尺寸约 200px
LOGO = ROOT / "assets" / "logo.png"
MASCOT = ROOT / "assets" / "mascot.png"
AVATAR_DIR = ROOT / "data" / "avatars"               # 用户上传头像（不进 git）


@lru_cache(maxsize=4)
def _data_uri(path: str) -> str:
    """把本地图片编码为 data URI（内联进 HTML，避免额外静态服务）"""
    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def logo_html(width: int = 190, margin: str = "0 auto 10px auto") -> str:
    """深色界面用 logo 的 HTML 片段（居中、可调宽）"""
    return (f'<img src="{_data_uri(str(LOGO_LIGHT))}" width="{width}" '
            f'style="display:block; margin:{margin};" alt="知途伴学">')


def mascot_html(width: int = 96, margin: str = "0 auto") -> str:
    return (f'<img src="{_data_uri(str(MASCOT))}" width="{width}" '
            f'style="display:block; margin:{margin};" alt="知途伴学吉祥物">')


def avatar_path(student_id: str) -> Path | None:
    """该学生的头像文件路径；未上传返回 None"""
    if AVATAR_DIR.is_dir():
        for f in sorted(AVATAR_DIR.glob(f"{student_id}.*")):
            if f.is_file():
                return f
    return None


def avatar_html(student_id: str, size: int = 44) -> str:
    """用户头像 data-URI（圆形裁剪由 CSS 处理）；未上传返回空串"""
    p = avatar_path(student_id)
    if p is None:
        return ""
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return (f'<img class="avatar-img" src="data:{mime};base64,{data}" '
            f'width="{size}" height="{size}" alt="头像">')

_CSS = """
<style>
:root {
    --bg: #070c18;
    --panel: rgba(255, 255, 255, 0.045);
    --panel-strong: rgba(255, 255, 255, 0.07);
    --line: rgba(120, 190, 255, 0.22);
    --line-strong: rgba(34, 211, 238, 0.55);
    --cyan: #22d3ee;
    --blue: #3b82f6;
    --text: #e8eef8;
    --muted: #8ea3c0;
}

/* ===== 底色：深空 + 全息光晕 ===== */
.stApp {
    background:
        radial-gradient(1100px 620px at 50% -12%, rgba(34, 211, 238, 0.16), transparent 62%),
        radial-gradient(900px 520px at 12% 8%, rgba(59, 130, 246, 0.14), transparent 58%),
        radial-gradient(1000px 600px at 92% 78%, rgba(14, 165, 233, 0.12), transparent 60%),
        var(--bg);
    background-attachment: fixed;
}
.stApp::before {
    content: "";
    position: fixed;
    inset: 0;
    background-image:
        linear-gradient(rgba(120, 190, 255, 0.05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(120, 190, 255, 0.05) 1px, transparent 1px);
    background-size: 46px 46px;
    mask-image: radial-gradient(circle at 50% 30%, black, transparent 78%);
    pointer-events: none;
    z-index: 0;
}
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {
    visibility: hidden;
}
.stApp > div { position: relative; z-index: 1; }

/* ===== 字体与标题 ===== */
html, body, [class*="css"], .stApp {
    font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
}
h1, h2, h3 { color: var(--text); letter-spacing: 0.01em; font-weight: 600; }
h1 {
    background: linear-gradient(92deg, #ffffff 8%, #a5e8ff 52%, #22d3ee 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}
p, label, span, div { color: var(--text); }
hr { border-color: var(--line); }

/* ===== 侧边栏：玻璃面板（固定常显，任何宽度不折叠） ===== */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(12, 22, 40, 0.92), rgba(8, 14, 28, 0.88));
    border-right: 1px solid var(--line);
    backdrop-filter: blur(14px);
    flex: 0 0 320px !important;
}
section[data-testid="stSidebar"] .stButton > button {
    justify-content: flex-start;
}
/* 收起/折叠控件全部隐藏：左栏常驻，不可收起
   （窄屏下 stSidebarCollapseButton 渲染成 div，选择器不能限定 button） */
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapseButton"] {
    display: none !important;
}
/* 画像页指标卡 hover 动效：上浮 + 青色辉光 */
[class*="st-key-profile_metric_"] {
    transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
}
[class*="st-key-profile_metric_"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 18px rgba(34, 211, 238, 0.18);
    border-color: rgba(34, 211, 238, 0.55) !important;
}
/* 窗口再窄也强制显示左栏（Streamlit 默认 992px 以下折叠；
   700px 以下主区会变 absolute 钉满全屏，拉回文档流保持并排） */
@media screen and (max-width: 991.98px) {
    section[data-testid="stSidebar"] {
        display: flex !important;
        width: 320px !important;
        min-width: 320px !important;
        position: relative !important;
    }
    .stMain, [data-testid="stMain"] {
        position: static !important;
        min-width: 0 !important;
    }
}

/* ===== 玻璃卡片（st.container(border=True) / st.container(key=...)）===== */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 16px;
    backdrop-filter: blur(12px);
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.06);
    padding: 0.5rem 0.4rem;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: var(--line-strong);
    box-shadow: 0 10px 34px rgba(34, 211, 238, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.08);
    transition: all 0.25s ease;
}

/* ===== 按钮：玻璃 + 霓虹 ===== */
.stButton > button, .stFormSubmitButton > button {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--line);
    border-radius: 12px;
    color: var(--text);
    font-weight: 500;
    transition: all 0.2s ease;
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
    border-color: var(--line-strong);
    color: #ffffff;
    box-shadow: 0 0 18px rgba(34, 211, 238, 0.28);
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
    background: linear-gradient(96deg, #0ea5e9, #22d3ee);
    border: none;
    color: #04121f;
    font-weight: 700;
    box-shadow: 0 6px 22px rgba(34, 211, 238, 0.35);
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
    box-shadow: 0 8px 30px rgba(34, 211, 238, 0.55);
    color: #04121f;
}

/* ===== 右上角账户入口：胶囊头像按钮 ===== */
.st-key-top_account { display: flex; justify-content: flex-end; }
.st-key-top_account .stButton > button {
    border-radius: 999px;
    padding: 4px 18px;
    font-size: 13px;
    color: #cfe0f5;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--line);
    gap: 6px;
}
.st-key-top_account .stButton > button:hover {
    color: #ffffff;
    border-color: var(--line-strong);
    box-shadow: 0 0 16px rgba(34, 211, 238, 0.28);
}
.st-key-top_account .stButton > button [data-testid="stIconMaterial"] {
    color: #22d3ee;
    font-size: 18px;
}

/* ===== 返回首页：紧凑小按钮，左对齐标题 ===== */
.back-home-bar { margin-bottom: -6px; }
.back-home-bar .stButton > button {
    padding: 3px 14px;
    font-size: 12.5px;
    color: #9fb6d4;
    background: rgba(255, 255, 255, 0.03);
}
.back-home-bar .stButton > button:hover { color: #ffffff; }

/* ===== 输入框 ===== */
.stTextInput input, .stNumberInput input, [data-testid="stChatInput"] textarea {
    background: rgba(255, 255, 255, 0.045);
    border: 1px solid var(--line);
    border-radius: 12px;
    color: var(--text);
}
.stTextInput input:focus, [data-testid="stChatInput"] textarea:focus {
    border-color: var(--line-strong);
    box-shadow: 0 0 0 1px var(--line-strong), 0 0 18px rgba(34, 211, 238, 0.2);
}
[data-testid="stChatInput"] {
    background: rgba(10, 18, 34, 0.72);
    border-top: 1px solid var(--line);
}

/* ===== 指标卡 ===== */
[data-testid="stMetric"] {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 14px 16px;
    backdrop-filter: blur(10px);
}
[data-testid="stMetricValue"] { color: #7fe6ff; font-weight: 700; }
[data-testid="stMetricLabel"] { color: var(--muted); }

/* ===== 对话气泡：助手=深色玻璃居左，学生=蓝色半透明居右 ===== */
[data-testid="stChatMessage"] {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 14px;
    backdrop-filter: blur(10px);
    padding: 4px 8px;
    max-width: 86%;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background: rgba(59, 130, 246, 0.28);
    border-color: rgba(96, 165, 250, 0.5);
    margin-left: auto;
}
[data-testid="stChatMessageAvatarAssistant"],
[data-testid="stChatMessageAvatarUser"] {
    background: linear-gradient(135deg, #0ea5e9, #6366f1);
    color: #ffffff;
    border-radius: 50%;
}
[data-testid="stChatMessageAvatarAssistant"] span,
[data-testid="stChatMessageAvatarUser"] span {
    color: #ffffff;
    font-size: 15px;
}

/* ===== 表格 / 展开面板 / 图表容器 ===== */
[data-testid="stDataFrame"], [data-testid="stTable"] {
    border: 1px solid var(--line);
    border-radius: 12px;
    overflow: hidden;
}
[data-testid="stExpander"] details {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 12px;
}
[data-testid="stExpander"] summary { color: var(--muted); }
[data-testid="stAlert"] {
    background: rgba(34, 211, 238, 0.07);
    border: 1px solid var(--line);
    border-radius: 12px;
}
/* 进度条 */
[data-testid="stProgress"] > div > div > div {
    background: linear-gradient(90deg, #0ea5e9, #22d3ee);
}

/* ===== 首页组件 ===== */
.hero-wrap { text-align: center; padding: 34px 0 10px 0; }
.hero-logo {
    display: inline-block;
    font-size: 13px; letter-spacing: 6px; color: #7fe6ff;
    border: 1px solid var(--line); border-radius: 999px;
    padding: 5px 18px 5px 24px; margin-bottom: 18px;
    background: rgba(34, 211, 238, 0.06);
}
.hero-title {
    font-size: 46px; font-weight: 700; margin: 0 0 10px 0; line-height: 1.15;
    background: linear-gradient(96deg, #ffffff 10%, #a5e8ff 55%, #22d3ee 100%);
    -webkit-background-clip: text; background-clip: text;
    -webkit-text-fill-color: transparent;
}
.hero-sub { color: var(--muted); font-size: 15px; margin: 0 0 6px 0; }
.hero-desc { color: #6f86a6; font-size: 13.5px; }
.stats-row { display: flex; justify-content: center; gap: 26px; flex-wrap: wrap;
             margin: 6px 0 4px 0; color: var(--muted); font-size: 13px; }
.stats-row b { color: #7fe6ff; font-weight: 600; }
.dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%;
       background: #22d3ee; margin-right: 6px; vertical-align: middle;
       box-shadow: 0 0 8px #22d3ee; }
.cards-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;
              margin: 8px 0 18px 0; }
.gcard {
    background: rgba(255, 255, 255, 0.045);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 16px 16px 14px 16px;
    backdrop-filter: blur(12px);
    transition: all 0.25s ease;
    min-height: 104px;
}
.gcard:hover {
    transform: translateY(-3px);
    border-color: var(--line-strong);
    box-shadow: 0 12px 30px rgba(34, 211, 238, 0.18);
}
.gcard .gicon { color: #22d3ee; margin-bottom: 8px; }
.gcard .gtitle { font-size: 15px; font-weight: 600; color: #eaf4ff; margin-bottom: 4px; }
.gcard .gdesc { font-size: 12.5px; color: #8296b3; line-height: 1.5; }

/* 首页功能卡片标题按钮：去按钮框、标题化，整行可点击 */
[class*="st-key-card_go_"] .stButton > button {
    justify-content: flex-start;
    text-align: left;
    padding: 2px 0;
    background: transparent;
    border: none;
    box-shadow: none;
    font-size: 15px;
    font-weight: 600;
    color: #eaf4ff;
    min-height: 0;
}
[class*="st-key-card_go_"] .stButton > button:hover {
    background: transparent;
    border: none;
    box-shadow: none;
    color: #7fe6ff;
}
[class*="st-key-card_go_"] .stButton > button [data-testid="stIconMaterial"] {
    color: #22d3ee;
    font-size: 18px;
    margin-right: 4px;
}
.section-title {
    font-size: 17px; font-weight: 600; color: #dbe9fb;
    margin: 22px 0 6px 0; padding-left: 10px; border-left: 3px solid #22d3ee;
}
.pill-row { display: flex; gap: 10px; flex-wrap: wrap; margin: 4px 0 10px 0; }
.pill {
    border: 1px solid var(--line); border-radius: 999px;
    padding: 5px 14px; font-size: 12.5px; color: #a9c3e0;
    background: rgba(255, 255, 255, 0.035);
}

/* ===== 登录页品牌栏能力卡 ===== */
[class*="st-key-brand_feat_"] [role="img"] {
    color: #22d3ee;
    font-size: 20px;
}
[class*="st-key-brand_feat_"] strong { color: #eaf4ff; }

/* ===== 侧边栏：项目名 / 用户信息卡 / 头像 ===== */
.side-appname {
    font-size: 16px; font-weight: 700; color: #eaf4ff;
    margin: 2px 0 12px 0; letter-spacing: 1px;
}
.avatar-img {
    border-radius: 50%; object-fit: cover;
    border: 2px solid var(--line-strong);
    display: block;
}
[class*="st-key-side_user"] [role="img"] {
    font-size: 44px; color: #22d3ee;
}
[class*="st-key-side_user"] .stButton > button {
    justify-content: center;
    font-size: 12.5px;
    padding: 2px 8px;
    color: #9fb6d4;
}

/* ===== 入场动效 ===== */
@keyframes riseIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
}
.gcard, [data-testid="stVerticalBlockBorderWrapper"] {
    animation: riseIn 0.38s ease both;
}

/* ===== 对话页顶部横幅 ===== */
.chat-banner {
    display: flex; justify-content: space-between; align-items: center; gap: 12px;
    padding: 12px 18px; margin-bottom: 10px;
    background: linear-gradient(96deg, rgba(14, 165, 233, 0.16), rgba(34, 211, 238, 0.08));
    border: 1px solid var(--line); border-radius: 14px;
    backdrop-filter: blur(10px);
}
.chat-banner .cb-left { display: flex; align-items: center; gap: 10px; }
.chat-banner .cb-name { font-size: 16px; font-weight: 700; color: #eaf4ff; }
.chat-banner .cb-phase {
    font-size: 12px; color: #7fe6ff; border: 1px solid var(--line);
    border-radius: 999px; padding: 2px 10px; background: rgba(34, 211, 238, 0.08);
}
.chat-banner .cb-right { font-size: 13px; color: var(--muted); }

/* ===== 快捷指令按钮图标 ===== */
[class*="st-key-quick_"] [data-testid="stIconMaterial"] {
    color: #22d3ee; font-size: 17px;
}
</style>
"""


def inject_theme():
    st.markdown(_CSS, unsafe_allow_html=True)
