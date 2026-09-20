"""开发期工具：Playwright 无头驱动 Streamlit 抓取项目书截图素材（Mock 离线模式）

前置：`streamlit run app.py` 已在运行（默认 http://localhost:8501）。
流程复刻 tests/test_e2e_mock.py 的 8 幕剧本：登录 → 4 问诊断 → 自适应测验（全对，
生成漂亮诊断报告）→ 讲义推进 → 答错进 L0 → 连错升 L1/L2/L3 → 变式检验 →
答对完成知识点 → 四个可视化页面 → 结束反思 → 重新登录验证记忆开场白。

题目答案通过 stem 匹配真实题库推算（答对/答错字母），不依赖任何 API Key。
产物：docs/screenshots/*.png（供项目书第五、六章插图）。

用法：python scripts/screenshot_pages.py [--base http://localhost:8501] [--id shotdemo]
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

QBANK = json.loads(
    (ROOT / "data" / "kg" / "questions.json").read_text(encoding="utf-8"))["questions"]

MSG = '[data-testid="stChatMessage"]'
CHAT_BOX = '[data-testid="stChatInput"] textarea'
SIDEBAR = '[data-testid="stSidebar"]'


def match_question(text):
    """用最长 stem 匹配当前题目；返回 (question, is_variant) 或 (None, False)"""
    best = None
    for q in QBANK:
        for src, is_var in ((q, False), (q.get("variant") or {}, True)):
            stem = (src.get("stem") or "").strip()
            if len(stem) >= 8 and stem in text:
                if best is None or len(stem) > len(best[1]):
                    best = (q, stem, is_var)
    return (best[0], best[2]) if best else (None, False)


def answer_letter(q, variant=False, wrong=False):
    src = q.get("variant") if variant else q
    ans = src.get("answer", "A")
    if wrong:
        return next(l for l in "ABCD" if l != ans)
    return ans


class ShotDriver:
    def __init__(self, page, out_dir, base):
        self.page = page
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.base = base
        self.msgs_seen = 0

    # ---------- 基础动作 ----------
    def latest_assistant(self):
        texts = [m.inner_text() for m in self.page.locator(MSG).all()]
        return texts[-1] if texts else ""

    def send(self, text, wait_for=None, timeout=20000):
        box = self.page.locator(CHAT_BOX)
        box.click()
        box.fill(text)
        box.press("Enter")
        self.page.locator(MSG).nth(self.msgs_seen + 1).wait_for(
            state="attached", timeout=timeout)
        if wait_for:
            self.page.get_by_text(wait_for).last.wait_for(timeout=timeout)
        self.msgs_seen += 2

    def shot(self, name, wait=1.2):
        self.page.wait_for_timeout(int(wait * 1000))
        path = self.out / name
        self.page.screenshot(path=str(path), full_page=True)
        print(f"  📸 {name}")

    def goto_page(self, label):
        nav = self.page.locator('[data-testid="stSidebarNav"]')
        nav.locator(f'a:has-text("{label}")').first.click()
        self.page.wait_for_timeout(1600)

    def sidebar_button(self, text):
        return self.page.locator(SIDEBAR).locator(
            f'button:has-text("{text}")').first

    def sidebar_text_input(self):
        return self.page.locator(SIDEBAR).locator('input[type="text"]').first


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8501")
    ap.add_argument("--id", default="shotdemo")
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    args = ap.parse_args()
    student_id = f"{args.id}_{int(time.time())}"

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000},
                                locale="zh-CN")
        # 等 Streamlit 起来（最多 30 秒）
        for _ in range(30):
            try:
                page.goto(args.base, timeout=5000)
                break
            except Exception:
                time.sleep(1)
        else:
            raise SystemExit("❌ Streamlit 未就绪，请先运行 streamlit run app.py")
        d = ShotDriver(page, args.out, args.base)

        print("== 幕0 初始状态（未登录） ==")
        d.shot("01_chat_初始登录页.png")

        print("== 幕1 登录 → 开场白 + 第一问 ==")
        d.sidebar_text_input().fill(student_id)
        d.sidebar_button("登录 / 开始学习").click()
        d.page.get_by_text("怎么称呼").last.wait_for(timeout=20000)
        d.msgs_seen = 1
        d.shot("02_chat_对话诊断.png")

        print("== 幕2 4 问对话诊断 ==")
        d.send("小明")
        d.send("广东理工学院 计算机专业")
        d.send("学过线性代数和概率统计")
        d.send("想重点学深度学习方向")

        print("== 幕3 自适应测验（答对推进主链，收敛最快） ==")
        quiz_shots = 0
        for turn in range(14):
            last = d.latest_assistant()
            if "开始学习" in last or "自由选择" in last:
                break
            q, is_var = match_question(last)
            ans = answer_letter(q, is_var) if q else "A"
            if q is None:
                print(f"  ⚠ 第{turn + 1}轮 stem 未匹配，回退答 A")
            d.send(ans)
            quiz_shots += 1
        else:
            raise SystemExit("❌ 测验 14 轮未收敛")
        print(f"  测验 {quiz_shots} 题 → 诊断报告 + 路径")
        d.page.get_by_text("开始学习").last.wait_for(timeout=20000)
        d.shot("04_chat_诊断报告与路径.png")

        print("== 幕4 讲义推进 → 巩固题 ==")
        for _ in range(6):
            d.send("好的")
            if "巩固题" in d.latest_assistant():
                break
        d.shot("05_chat_讲义教学.png")
        d.page.get_by_text("巩固题").last.wait_for(timeout=20000)

        print("== 幕5 答错 → L0 脚手架 ==")
        q, is_var = match_question(d.latest_assistant())
        wrong = answer_letter(q, is_var, wrong=True) if q else "C"
        d.send(wrong, wait_for="答错了也没关系")
        d.shot("06_chat_脚手架L0.png")

        print("== 幕6 连错升级 L1→L2→L3 → 变式 ==")
        d.send(wrong)
        d.send(wrong)
        d.send(wrong)
        d.shot("07_chat_脚手架L3.png")
        d.send(wrong, wait_for="换个形式")
        d.shot("08_chat_变式检验.png")

        print("== 幕7 变式答对 → 知识点完成 ==")
        q2, is_var2 = match_question(d.latest_assistant())
        good = answer_letter(q2, is_var2) if q2 else "B"
        d.send(good, wait_for="回答正确")
        d.shot("09_chat_知识点完成.png")

        print("== 幕8 四个可视化页面 ==")
        for label, name in [("学生画像", "10_学生画像页.png"),
                            ("学习路径", "11_学习路径页.png"),
                            ("知识图谱", "12_知识图谱页.png"),
                            ("状态探针", "13_状态探针页.png")]:
            d.goto_page(label)
            d.shot(name, wait=1.8)
        d.goto_page("对话学习")

        print("== 幕9 结束会话 → 反思 ==")
        d.send("结束")
        d.shot("14_chat_会话反思.png")

        print("== 幕10 登出 → 重新登录 → 记忆开场白 ==")
        d.sidebar_button("登出").click()
        d.page.wait_for_timeout(1200)
        d.sidebar_text_input().fill(student_id)
        d.sidebar_button("登录 / 开始学习").click()
        d.page.get_by_text("欢迎回来").last.wait_for(timeout=20000)
        d.shot("15_chat_记忆欢迎回来.png")

        browser.close()
    print(f"✅ 完成：{len(list(Path(args.out).glob('*.png')))} 张截图 → {args.out}")


if __name__ == "__main__":
    main()
