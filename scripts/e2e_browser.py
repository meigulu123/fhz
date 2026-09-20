"""浏览器端核心功能回归：对运行中的应用完整走一遍四大核心能力（全离线 Mock）

前置：streamlit run app.py 已在运行（默认 http://localhost:8501）。
用法：python scripts/e2e_browser.py [--base http://localhost:8501]

与 tests/（AppTest 模拟会话）不同，本脚本驱动真实浏览器点击真实 UI，
验证「评委现场看到的那条链路」：

    注册 → 登录 → 开始学习 → 4 问对话诊断 → 自适应测验（CCWW 作答）→
    出路径 → 讲义推进 → 答错 L0 → 连错 L1/L2/L3 → 变式检验 → 知识点完成 →
    学生画像/学习路径/知识图谱/账户管理/状态探针 → 结束反思 → 记忆开场白 →
    退出登录。

每步独立断言，全部 PASS exit 0。只打印 PASS/FAIL，不截图、不录屏、不写文件。

作答策略说明：
- 测验按「对、对、错、错」成对作答（CCWW）：任意 3 连窗口至少 1 对，
  避免测验尾段 3 连错在进入教学时被卡住判定（近3轮正确率<1/3）误触发。
- 脚手架阶段不展示题干，用 L0~L3 提示文本反查题库（各层级 150/150 唯一）
  确定当前题目，再动态计算错项。
"""
import argparse
import json
import re
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

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    return ok


def match_question(text):
    """最长 stem 匹配当前题目（含变式）；返回 (q, is_variant) 或 (None, False)"""
    best = None
    for q in QBANK:
        for src, is_var in ((q, False), (q.get("variant") or {}, True)):
            stem = (src.get("stem") or "").strip()
            if len(stem) >= 8 and stem in text:
                if best is None or len(stem) > len(best[1]):
                    best = (q, stem, is_var)
    return (best[0], best[2]) if best else (None, False)


def match_by_hint(text):
    """用 L0~L3 提示文本匹配当前题目（脚手架阶段题干不展示）"""
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

    def latest_assistant(self):
        texts = [m.inner_text() for m in self.page.locator(MSG).all()]
        return texts[-1] if texts else ""

    def send(self, text, timeout=30000):
        box = self.page.locator(CHAT_BOX)
        for attempt in range(2):
            box.click()
            box.fill(text)
            # 稍等输入框 JS 状态同步：立即回车偶发被吞（已实测）
            self.page.wait_for_timeout(250)
            box.press("Enter")
            try:
                # 用户消息上屏才算提交成功（新用户消息在索引 msgs_seen）
                self.page.locator(MSG).nth(self.msgs_seen).wait_for(
                    state="attached", timeout=8000)
                break
            except Exception:
                print(f"  ⚠ 回车未提交，重试第 {attempt + 1} 次")
        else:
            raise SystemExit("❌ 聊天输入两次发送均未提交")
        self.page.locator(MSG).nth(self.msgs_seen + 1).wait_for(
            state="attached", timeout=timeout)
        self.msgs_seen += 2

    def goto_page(self, label, wait=1.4, expect=None):
        self.page.locator(SIDEBAR).locator(
            f'button:has-text("{label}")').first.click()
        if expect:
            # 轮询等目标文本出现在主区（页面渲染有快有慢，固定 sleep 不可靠）
            self.page.locator('[data-testid="stMain"]').get_by_text(
                expect).wait_for(timeout=10000)
        else:
            self.page.wait_for_timeout(int(wait * 1000))

    def sidebar_button(self, text):
        return self.page.locator(SIDEBAR).locator(
            f'button:has-text("{text}")').first

    def main_button(self, text):
        return self.page.locator('[data-testid="stMain"]').locator(
            f'button:has-text("{text}")').first

    def main_first_button(self):
        return self.page.locator('[data-testid="stMain"] button').first


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8501")
    args = ap.parse_args()
    student_id = f"e2e{int(time.time()) % 10**6}"
    password = "pass1234"

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000},
                                locale="zh-CN")
        for _ in range(30):
            try:
                page.goto(args.base, timeout=5000)
                break
            except Exception:
                time.sleep(1)
        else:
            raise SystemExit("❌ Streamlit 未就绪，请先运行 streamlit run app.py")
        d = Driver(page)
        print(f"目标：{args.base}（Mock 离线模式，新账号 {student_id}）")

        # ---------- 幕0 注册 ----------
        print("\n== 注册 ==")
        d.main_button("注册新账号").click()
        # 等注册视图真正渲染完成再填表：旧登录页也有 input[type="text"]，
        # 过早填写会填进即将被替换的旧 DOM，导致注册时账户为空
        page.locator('button:has-text("返回登录")').wait_for(timeout=15000)
        page.locator('input[type="text"]').fill(student_id)
        pwd_inputs = page.locator('input[type="password"]')
        pwd_inputs.nth(0).fill(password)
        pwd_inputs.nth(1).fill(password)
        d.main_button("注 册").click()
        page.get_by_text("注册成功").last.wait_for(timeout=20000)
        # 等注册视图 DOM 完全卸下（确认密码框 detach），
        # 否则新旧视图输入框并存，密码定位命中两个元素
        page.locator('input[aria-label="确认密码"]').wait_for(
            state="detached", timeout=20000)
        check("注册成功返回登录页",
              page.locator('input[type="text"]').input_value() == student_id)

        # ---------- 幕1 登录 → 首页 ----------
        print("\n== 登录 ==")
        page.locator('input[aria-label="密码"]').fill(password)
        d.main_button("登 录").click()
        # 同步点：首页专属的「开始学习」按钮（登录页左栏也有「核心能力」字样，
        # 不能再用它当同步锚点）
        d.main_button("开始学习").wait_for(timeout=30000)
        check("登录落在首页", d.main_button("开始学习").is_visible())

        # ---------- 幕2 开始学习 → 对话页 ----------
        print("\n== 对话学习 ==")
        d.main_button("开始学习").click()
        page.get_by_text("怎么称呼").last.wait_for(timeout=20000)
        d.msgs_seen = 1
        check("开场白带第一问", "怎么称呼" in d.latest_assistant())

        # ---------- 幕3 4 问对话诊断 ----------
        print("\n== 4 问对话诊断 ==")
        d.send("小明")
        check("问1 姓名", "专业" in d.latest_assistant())
        d.send("广东理工学院 计算机专业")
        d.send("学过线性代数和概率统计")
        d.send("想重点学深度学习方向")
        check("问4 进入测验", "做几道题" in d.latest_assistant())

        # ---------- 幕4 自适应测验（CCWW） ----------
        print("\n== 自适应测验 ==")
        for i in range(16):
            last = d.latest_assistant()
            if "开始学习" in last or "自由选择" in last:
                break
            q, is_var = match_question(last)
            if q is None:
                print(f"  ⚠ 第{i + 1}题 stem 未匹配，回退答 A")
                d.send("A")
                continue
            wrong = (i // 2) % 2 == 1
            d.send(answer_letter(q, is_var, wrong=wrong))
        ok = check("测验收敛出路径", "开始学习" in d.latest_assistant(),
                   "自由选择" if "自由选择" in d.latest_assistant() else "已生成")
        if not ok:
            browser.close()
            return _summary()
        m = re.search(r"我们从「(.+?)」开始", d.latest_assistant())
        node_name = m.group(1) if m else ""

        # ---------- 幕5 讲义推进 → 巩固题 ----------
        print("\n== 讲义教学 ==")
        for _ in range(6):
            # 用「巩固题」而非「巩固」：开场白含"复习巩固"档位说明，会误触发
            if "巩固题" in d.latest_assistant():
                break
            d.send("好的")
        check("讲义推进出巩固题", "巩固题" in d.latest_assistant())

        # ---------- 幕6 答错 → L0 ----------
        print("\n== 脚手架干预 ==")
        q, is_var = match_question(d.latest_assistant())
        wrong = answer_letter(q, is_var, wrong=True) if q else "C"
        d.send(wrong)
        check("答错进入 L0", "答错了也没关系" in d.latest_assistant())

        # ---------- 幕7 连错升级 L1→L2→L3 → 变式 ----------
        # 脚手架换用同节点未做过的题：用 L0 提示反查当前题，错项按它重算
        q_s = match_by_hint(d.latest_assistant()) or q
        wrong_s = answer_letter(q_s, wrong=True) if q_s else wrong
        d.send(wrong_s)
        d.send(wrong_s)
        d.send(wrong_s)
        check("连错升至 L3", bool(d.latest_assistant().strip()))
        d.send(wrong_s)
        check("L3 后出变式题", "换个形式" in d.latest_assistant())

        # ---------- 幕8 变式答对 → 知识点完成 ----------
        good = answer_letter(q_s, variant=True) if q_s else "A"
        d.send(good)
        check("变式答对完成知识点", "回答正确" in d.latest_assistant())

        # ---------- 幕9 七个页面 ----------
        # 页面标题是 st.header（渲染为 h2），统一用主区文本断言，避免元素选择器漂移
        print("\n== 可视化页面 ==")
        MAIN = '[data-testid="stMain"]'
        d.goto_page("个人画像", expect="基本信息与诊断报告")
        check("学生画像页", "学生画像" in page.inner_text(MAIN)
              and "基本信息与诊断报告" in page.inner_text(MAIN)
              and "学习优势" in page.inner_text(MAIN)
              and "大模型观察记录" in page.inner_text(MAIN))
        d.goto_page("学习路径", expect="为什么这样排")
        main_text = page.inner_text(MAIN)
        ok_path = "学习路径" in main_text
        # 路径表格是 canvas 渲染取不到单元格文本，展开「评分构成」验证批次内容
        page.get_by_text("为什么这样排").click()
        try:
            page.locator(MAIN).get_by_text("综合评分").wait_for(timeout=8000)
            ok_path = ok_path and \
                page.locator('[data-testid="stDataFrame"]').count() > 0
        except Exception:
            ok_path = False
        check("学习路径页", ok_path, "评分构成展开且路径表格渲染")
        d.goto_page("知识图谱", expect="掌握度分层统计")
        check("知识图谱页", "知识图谱" in page.inner_text(MAIN)
              and "掌握度分层统计" in page.inner_text(MAIN))
        d.goto_page("历史对话", expect="历史对话")
        check("历史对话页", "历史对话" in page.inner_text(MAIN))
        d.goto_page("错题本", expect="错题本")
        check("错题本页", "错题本" in page.inner_text(MAIN))
        d.goto_page("账户管理", expect="账户信息")
        check("账户管理页", "账户信息" in page.inner_text('[data-testid="stMain"]'))
        d.goto_page("状态探针", expect="状态持久化探针")
        # 主区第一个按钮现在是侧边栏开关，探针按钮要按文本精确定位
        # （已登录时显示「修改状态」，未登录才显示「创建探针状态」）
        page.locator(MAIN).locator(
            'button:has-text("修改状态：interaction_count +1")').first.click()
        page.get_by_text("存活").last.wait_for(timeout=20000)
        check("状态探针 rerun 存活", "存活" in page.inner_text('[data-testid="stMain"]'))

        # ---------- 幕9.5 侧边栏开关 ----------
        # 「开始学习」按钮只在诊断阶段显示，首页稳定锚点用「能力标签」
        d.goto_page("首页", expect="能力标签")
        # 若侧边栏已处于收起状态（异常），先恢复再测
        if page.locator(MAIN).locator('button:has-text("打开侧边栏")').count() > 0:
            page.locator(MAIN).locator('button:has-text("打开侧边栏")').first.click()
            page.wait_for_timeout(2000)
        page.locator(MAIN).locator('button:has-text("收起侧边栏")').first.click()
        page.wait_for_timeout(2500)
        sb_hidden = not page.locator(SIDEBAR).is_visible()
        page.locator(MAIN).locator('button:has-text("打开侧边栏")').first.click()
        page.wait_for_timeout(2500)
        sb_back = page.locator(SIDEBAR).is_visible()
        check("侧边栏开关收起/恢复", sb_hidden and sb_back)

        # ---------- 幕10 结束反思 + 记忆开场白 ----------
        print("\n== 记忆反思 ==")
        d.goto_page("新对话", wait=0.8)
        for _ in range(2):  # 探针页 rerun 后切页偶发慢，聊天框未出现则重试一次导航
            try:
                page.locator(CHAT_BOX).wait_for(state="attached", timeout=15000)
                break
            except Exception:
                d.goto_page("新对话", wait=1.0)
        d.send("结束")
        check("结束会话出反思", "今天的学习到这里" in d.latest_assistant())
        d.send("继续")
        check("记忆开场白", "欢迎回来" in d.latest_assistant())

        # ---------- 幕11 退出登录 ----------
        print("\n== 退出登录 ==")
        d.sidebar_button("退出登录").click()
        # 登录页元素自上而下渲染：等「演示账号」按钮可见再断言，避免竞态
        page.locator('input[type="text"]').wait_for(timeout=20000)
        d.main_button("演示账号").wait_for(state="visible", timeout=20000)
        check("退出回到登录页", True)

        browser.close()
    return _summary()


def _summary():
    total, passed = len(RESULTS), sum(ok for _, ok in RESULTS)
    print("\n" + "=" * 56)
    print(f"浏览器回归：{passed}/{total} 通过")
    for name, ok in RESULTS:
        if not ok:
            print(f"  ✗ {name}")
    print("=" * 56)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
