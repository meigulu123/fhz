"""优化handle方法，添加性能日志"""
from pathlib import Path

p = Path('src/agent/orchestrator.py')
content = p.read_text(encoding='utf-8')

# 找到handle方法开始
start = content.find('    def handle(self, state: AgentState, text: str) -> tuple:')
# 找到下一个方法定义作为结束
end = content.find('    # ==================== 感知 ====================')

print(f'Start: {start}, End: {end}')

old_method = content[start:end]
print(f'Old method length: {len(old_method)}')

new_method = '''    def handle(self, state: AgentState, text: str) -> tuple:
        import time as _time
        t0 = _time.time()
        text = (text or "").strip()
        if not text:
            return "我在的，想说什么都可以，比如聊聊学习进度或你卡住的地方。", self._payload(state)
        state.interaction_count += 1
        # 空闲跟进：学习阶段离开 ≥5 分钟后回来，先让大模型更新一次画像再继续
        if state.phase in (TEACHING, INTERVENING) and self._idle_update_due(state):
            self._update_profile_from_conversation(state, "idle")
        intent = self._classify(text)
        t1 = _time.time()
        try:
            state.memory_ctx = build_context(self.mem, state.student_id, text,
                                             self.mem.last_reflection(state.student_id))
        except Exception as e:
            logger.warning("记忆检索失败，跳过记忆上下文: %s", e)
            state.memory_ctx = ""
        kind = intent.get("intent", "answer")
        dispatch = {IDLE: self._idle_turn, DIAGNOSING: self._diagnose_turn,
                    QUIZZING: self._quiz_turn, TEACHING: self._teach_turn,
                    INTERVENING: self._intervene_turn, PRACTICING: self._practice_turn}
        if kind == "end_session" and state.phase not in (IDLE, REFLECTING, PRACTICING):
            reply, payload = self._end_session(state)
        elif state.phase == REFLECTING:
            state.reset_for_new_session()
            reply, payload = self.start_session(state)
        elif kind == "practice" and state.phase != PRACTICING:
            reply, payload = self._start_practice(state, text)
        elif kind == "question":
            ans = self._answer_question(state, text)
            reply, payload = ans if ans is not None else \\
                dispatch.get(state.phase, self._teach_turn)(state, text, kind)
        else:
            reply, payload = dispatch.get(state.phase, self._teach_turn)(state, text, kind)
        state.history.append({"role": "user", "content": text})
        state.history.append({"role": "assistant", "content": reply})
        t2 = _time.time()
        logger.debug("handle完成: phase=%s intent=%s 意图耗时=%.1fms 总耗时=%.1fms",
                     state.phase, kind, (t1-t0)*1000, (t2-t0)*1000)
        return reply, payload

'''

new_content = content[:start] + new_method + content[end:]
p.write_text(new_content, encoding='utf-8')
print(f'New file length: {len(new_content)}')
print('Done')
