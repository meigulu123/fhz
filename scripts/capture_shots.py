"""项目书截图采集：驱动真实浏览器走完整剧本，在关键节点截图（Mock 离线模式）

前置：Mock 模式服务已运行（http://localhost:8501）。
用法：python scripts/capture_shots.py
输出：docs/assets/shots/*.png（约 18 张，1600×1000 视口 ×2 倍缩放，打印清晰）

流程与 e2e_browser.py 一致（注册→诊断→测验→路径→教学→L0-L3→页面→反思→记忆），
不同点：不跑断言，只在每个关键节点 page.screenshot 存图；账号每次新建，内容确定性好。
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SHOTS = ROOT / "docs" / "assets" / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)

QBANK = json.loads(
    (ROOT / "data" / "kg" / "questions.json").read_text(encoding="utf-8"))["questions"]

MSG = '[data-testid="stChatMessage"]'
CHAT_BOX = '[data-testid="stChatInput"] textarea'
SIDEBAR = '[data-testid="stSidebar"]'
MAIN = '[data-testid="stMain"]'


def match_question(text):
    best = None
    for q in QBANK:
        for src, is_var in ((q, False), (q.get("variant") or {}, True)):
            stem = (src.get("stem") or "").strip()
            if len(stem) >= 8 and stem in text:
                if best is None or len(stem) > len(best[1]):
                    best = (q, stem, is_var)
    return (best[0], best[2]) if best else (None, False)


def match_by_hint(text):
    best = None
    for q in QBANK:
        for lv in ("L0", "L1", "L2", "L3"):
            hint = (q["hints"].get(lv) or "").strip()
            if len(hint) >= 8 and hint in text:
                if best is None or len(hint) > len(best[1]):
                    best = (q, hint)
    return best[0] if best else None


def answer_letter(q, variant=False, wrong=False):
    src = q.get("variant") if variant else q
    ans = src.get("answer", "A")
    return next(l for l in "ABCD" if l != ans) if wrong else ans


class Driver:
    def __init__(self, page):
        self.page = page
        self.msgs_seen = 0
        self.shot_no = 0

    def shot(self, name):
        self.shot_no += 1
        path = SHOTS / f"s{self.shot_no:02d}_{name}.png"
        self.page.screenshot(path=path)
        print(f"  [SHOT] {path.name}")
        return path

    def latest_assistant(self):
        texts = [m.inner_text() for m in self.page.locator(MSG).all()]
        return texts[-1] if texts else ""

    def send(self, text, timeout=30000):
        box = self.page.locator(CHAT_BOX)
        for attempt in range(2):
            box.click()
            box.fill(text)
            self.page.wait_for_timeout(250)
            box.press("Enter")
            try:
                self.page.locator(MSG).nth(self.msgs_seen).wait_for(
                    state="attached", timeout=8000)
                break
            except Exception:
                print(f"  [!] 回车未提交，重试第 {attempt + 1} 次")
        else:
            raise SystemExit("❌ 聊天输入两次发送均未提交")
        self.page.locator(MSG).nth(self.msgs_seen + 1).wait_for(
            state="attached", timeout=timeout)
        self.msgs_seen += 2

    def goto_page(self, label, wait=1.4, expect=None):
        self.page.locator(SIDEBAR).locator(
            f'button:has-text("{label}")').first.click()
        if expect:
            self.page.locator(MAIN).get_by_text(
                expect).wait_for(timeout=10000)
        else:
            self.page.wait_for_timeout(int(wait * 1000))

    def main_button(self, text):
        return self.page.locator(MAIN).locator(
            f'button:has-text("{text}")').first


def main():
    from playwright.sync_api import sync_playwright
    student_id = f"shot{int(time.time()) % 10**6}"
    password = "pass1234"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000},
                                device_scale_factor=2, locale="zh-CN")
        for _ in range(30):
            try:
                page.goto("http://localhost:8501", timeout=5000)
                break
            except Exception:
                time.sleep(1)
        else:
            raise SystemExit("❌ Streamlit 未就绪")
        d = Driver(page)
        print(f"新账号 {student_id}（Mock 模式）")

        # s01 登录页
        d.main_button("演示账号").wait_for(state="visible", timeout=20000)
        d.shot("登录页")

        # 注册
        d.main_button("注册新账号").click()
        page.locator('button:has-text("返回登录")').wait_for(timeout=15000)
        page.locator('input[type="text"]').fill(student_id)
        pwd = page.locator('input[type="password"]')
        pwd.nth(0).fill(password)
        pwd.nth(1).fill(password)
        d.main_button("注 册").click()
        page.get_by_text("注册成功").last.wait_for(timeout=20000)
        page.locator('input[aria-label="确认密码"]').wait_for(
            state="detached", timeout=20000)

        # 登录 → 首页
        page.locator('input[aria-label="密码"]').fill(password)
        d.main_button("登 录").click()
        d.main_button("开始学习").wait_for(timeout=30000)
        d.shot("首页")

        # 开始学习 → 开场白第一问
        d.main_button("开始学习").click()
        page.get_by_text("怎么称呼").last.wait_for(timeout=20000)
        d.msgs_seen = 1
        d.shot("诊断第一问")

        # 4 问对话诊断
        d.send("小明")
        d.send("广东理工学院 计算机专业")
        d.send("学过线性代数和概率统计")
        d.send("想重点学深度学习方向")
        page.get_by_text("做几道题").last.wait_for(timeout=20000)
        d.shot("诊断四问完成")

        # 自适应测验（CCWW），第 1 题出现时截图
        quiz_shot = False
        for i in range(16):
            last = d.latest_assistant()
            if "开始学习" in last or "自由选择" in last:
                break
            if not quiz_shot and re.search(r"[ABCD][．.、]?", last):
                d.shot("自适应测验题")
                quiz_shot = True
            q, is_var = match_question(last)
            if q is None:
                d.send("A")
                continue
            wrong = (i // 2) % 2 == 1
            d.send(answer_letter(q, is_var, wrong=wrong))
        # 诊断报告 + 首条路径
        page.get_by_text("开始学习").last.wait_for(timeout=20000)
        d.shot("诊断报告与路径生成")
        m = re.search(r"我们从「(.+?)」开始", d.latest_assistant())
        node_name = m.group(1) if m else ""

        # 讲义推进（截图讲义界面）
        for _ in range(2):
            if "巩固题" in d.latest_assistant():
                break
            d.send("好的")
        d.shot("讲义讲解")
        for _ in range(4):
            if "巩固题" in d.latest_assistant():
                break
            d.send("好的")

        # 答错 → L0 反问
        q, is_var = match_question(d.latest_assistant())
        wrong = answer_letter(q, is_var, wrong=True) if q else "C"
        d.send(wrong)
        page.get_by_text("答错了也没关系").last.wait_for(timeout=20000)
        d.shot("L0苏格拉底反问")

        # 连错升级 → L3 分步解析 → 变式题
        q_s = match_by_hint(d.latest_assistant()) or q
        wrong_s = answer_letter(q_s, wrong=True) if q_s else wrong
        d.send(wrong_s)
        d.send(wrong_s)
        d.send(wrong_s)
        d.shot("L3分步解析")
        d.send(wrong_s)
        page.get_by_text("换个形式").last.wait_for(timeout=20000)
        d.shot("变式检验题")

        # 变式答对 → 完成
        good = answer_letter(q_s, variant=True) if q_s else "A"
        d.send(good)

        # 学生画像页（两张：顶部雷达区 / 下方趋势与观察记录）
        d.goto_page("个人画像", expect="基本信息与诊断报告")
        d.shot("画像页雷达与报告")
        page.locator(MAIN).get_by_text("大模型观察记录").scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        d.shot("画像页趋势与观察记录")

        # 学习路径页（含评分构成展开）
        d.goto_page("学习路径", expect="为什么这样排")
        d.shot("学习路径页")
        page.get_by_text("为什么这样排").click()
        try:
            page.locator(MAIN).get_by_text("综合评分").wait_for(timeout=8000)
            d.shot("路径评分构成")
        except Exception:
            print("  ⚠ 评分构成未展开，跳过截图")

        # 知识图谱页
        d.goto_page("知识图谱", expect="掌握度分层统计")
        d.shot("知识图谱页")

        # 错题本 + 历史对话
        d.goto_page("错题本", expect="错题本")
        d.shot("错题本页")
        d.goto_page("历史对话", expect="历史对话")
        d.shot("历史对话页")

        # 状态探针页（先点按钮触发 rerun）
        d.goto_page("状态探针", expect="状态持久化探针")
        page.locator(MAIN).locator(
            'button:has-text("修改状态：interaction_count +1")').first.click()
        page.get_by_text("存活").last.wait_for(timeout=20000)
        d.shot("状态探针页")

        # 结束反思 → 记忆开场白
        d.goto_page("新对话", wait=0.8)
        for _ in range(2):
            try:
                page.locator(CHAT_BOX).wait_for(state="attached", timeout=15000)
                break
            except Exception:
                d.goto_page("新对话", wait=1.0)
        d.send("结束")
        page.get_by_text("今天的学习到这里").last.wait_for(timeout=20000)
        d.shot("会话结束反思")
        d.send("继续")
        page.get_by_text("欢迎回来").last.wait_for(timeout=20000)
        d.shot("记忆开场白")

        browser.close()
    print(f"\n完成：{d.shot_no} 张截图 → docs/assets/shots/")


if __name__ == "__main__":
    main()
