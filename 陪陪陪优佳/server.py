#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
陪优佳 — Web API 服务
Medical Terminology Knowledge Base Web Server

启动: python server.py
访问: http://localhost:5000
"""

import json
import sys
import os
import io
import re
import random
import time
from collections import defaultdict

try:
    import jieba
    _JIEBA_AVAILABLE = True
except ImportError:
    _JIEBA_AVAILABLE = False

# 修复 Windows 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from flask_cors import CORS

# 导入知识库模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from med_term_kb import MedicalKnowledgeBase, MedicalTermSearch, format_disease_response

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
CORS(app)

# 全局知识库
kb = None
search = None

# 预计算 — NER 用，避免每次请求排序 8815 个疾病名
_DISEASES_BY_LENGTH_DESC = []

# 会话记忆存储（简单的内存字典，session_id → 最近 N 轮对话）
# 生产环境应换 Redis
_session_memory = defaultdict(list)  # session_id -> [(role, text, timestamp), ...]
MAX_MEMORY_TURNS = 10

# 查询结果缓存（query_hash → {result, cached_at}）
# 避免完全相同查询重复计算
_query_cache = {}
QUERY_CACHE_SIZE = 200
QUERY_CACHE_TTL = 300  # 5 分钟


def _cache_key(query, mode):
    """生成缓存 key"""
    return f"{mode}:{query.strip().lower()}"


def _cache_get(query, mode):
    """从缓存获取结果，TTL 过期返回 None"""
    key = _cache_key(query, mode)
    entry = _query_cache.get(key)
    if not entry:
        return None
    if time.time() - entry['cached_at'] > QUERY_CACHE_TTL:
        del _query_cache[key]
        return None
    return entry['result']


def _cache_set(query, mode, result):
    """写入缓存，超出上限时淘汰最旧的条目"""
    key = _cache_key(query, mode)
    _query_cache[key] = {'result': result, 'cached_at': time.time()}
    # LRU 淘汰
    if len(_query_cache) > QUERY_CACHE_SIZE:
        oldest_key = min(_query_cache, key=lambda k: _query_cache[k]['cached_at'])
        del _query_cache[oldest_key]


def _update_memory(session_id, role, text):
    """记录对话到会话记忆，自动清理过期会话"""
    _session_memory[session_id].append({
        'role': role,
        'text': text[:500],  # 截断长文本
        'time': time.time()
    })
    # 保持最近 N 轮
    if len(_session_memory[session_id]) > MAX_MEMORY_TURNS * 2:
        _session_memory[session_id] = _session_memory[session_id][-MAX_MEMORY_TURNS * 2:]

    # 定期清理过期会话（超过 1 小时未活动）
    now = time.time()
    expired = [sid for sid, msgs in _session_memory.items()
               if now - (msgs[-1]['time'] if msgs else now) > 3600]
    for sid in expired:
        del _session_memory[sid]


def init_kb():
    global kb, search, _DISEASES_BY_LENGTH_DESC
    print("正在加载医疗知识库...")
    kb = MedicalKnowledgeBase()
    kb.load_all()
    search = MedicalTermSearch(kb)

    # 预计算 NER 用的疾病名排序（按长度降序，一次计算，全局复用）
    _DISEASES_BY_LENGTH_DESC = sorted(kb.diseases.keys(), key=len, reverse=True)
    print(f"  [OK] NER 疾病索引: {len(_DISEASES_BY_LENGTH_DESC)} 个")

    # jieba 自带词典已覆盖大多数中文词，无需额外加载
    if _JIEBA_AVAILABLE:
        print(f"  [OK] jieba 分词已就绪（默认词典）")

    print("知识库加载完成！")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stats")
def stats():
    return jsonify({
        "diseases": len(kb.diseases),
        "qa_pairs": len(kb.qa_pairs),
        "terms": len(kb.term_dict),
        "symptoms": len(kb.symptom_map),
        "drugs": len(kb.drug_map),
        "departments": len(kb.dept_map),
    })


# ── 健康咨询意图识别 ──
def _detect_health_aspect(query):
    """检测用户问的是哪个具体健康方面，用于智能聚焦回复"""
    q = query.lower()

    # 每个关键词有不同权重：strong=3（高置信，如"降压药"）、normal=1（一般词）
    aspects_weighted = {
        'diet': [
            (['饮食', '忌口', '食谱', '营养', '不能吃', '能吃什么', '减盐', '低盐', '低脂', '低糖',
              '清淡', '膳食', '烹饪', '维生素', '矿物质', '补一补', '食补', '食疗', '高蛋白'], 3),
            (['吃', '喝', '食物', '水果', '蔬菜', '肉', '餐', '饭', '早餐', '午餐', '晚餐',
              '多吃', '少吃', '补', '汤', '口味', '炒', '炖', '蒸', '纤维', '喝水', '饮水', '茶', '咖啡'], 1),
        ],
        'exercise': [
            (['运动', '锻炼', '健身', '游泳', '瑜伽', '太极', '有氧', '无氧', '拉伸', '热身',
              '运动量', '运动强度', '怎么锻炼', '什么运动', '不能运动'], 3),
            (['活动', '走路', '跑步', '散步', '体力', '久坐'], 1),
        ],
        'medication': [
            (['吃药', '用药', '药物', '剂量', '副作用', '降压药', '降糖药', '胰岛素', '处方药',
              '药物相互作用', '服药时间', '药量', '停药', '遵医嘱', '药盒', '分药', '怎么吃'], 3),
            (['药', '饭前', '饭后', '空腹', '忘记吃'], 1),
        ],
        'lifestyle': [
            (['睡眠', '作息', '饮酒', '抽烟', '吸烟', '喝酒', '熬夜', '午休', '泡脚',
              '情绪', '压力', '放松', '心情'], 3),
            (['生活', '习惯', '休息', '洗澡', '按摩', '旅游', '出行', '高原', '温差'], 1),
        ],
        'prevention': [
            (['预防', '并发症', '恶化', '复发', '怎么防止', '会不会加重', '会不会严重', '危险因素', '风险'], 3),
            (['避免', '注意', '保养'], 1),
        ],
        'daily_care': [
            (['日常', '护理', '康复', '出院', '监测', '自测', '血糖仪', '血压计', '复查', '随访',
              '恢复', '在家', '自我', '照顾'], 3),
            (['记录', '体温', '体重'], 1),
        ],
    }

    scores = {}
    for aspect, keyword_groups in aspects_weighted.items():
        score = 0
        for keywords, weight in keyword_groups:
            for kw in keywords:
                if kw in q:
                    score += weight
        if score > 0:
            scores[aspect] = score

    # 当 medication 和 diet 同时命中时，如果 query 含"药"字，提升 medication
    if 'medication' in scores and 'diet' in scores:
        if any(w in q for w in ['药', '剂量', '服用', '口服', '处方']):
            scores['medication'] += 4

    if scores:
        return max(scores, key=scores.get)
    return 'general'


def _aspect_question_map():
    """每个方面对应的扩展搜索问题（提升QA匹配率）"""
    return {
        'diet': '饮食 营养 食谱 忌口 吃什么',
        'exercise': '运动 锻炼 活动 康复训练',
        'medication': '用药 吃药 剂量 副作用',
        'lifestyle': '生活习惯 作息 睡眠 情绪',
        'prevention': '预防 注意事项 避免 保养',
        'daily_care': '日常护理 康复 出院 自我监测',
    }


@app.route("/api/search", methods=["POST"])
def api_search():
    """统一搜索接口（带意图识别、对话记忆、智能聚焦回复）"""
    data = request.get_json()
    query = data.get("query", "").strip()
    mode = data.get("mode", "auto")  # auto, disease, symptom, drug, qa, term
    session_id = data.get("session_id", "default")
    history = data.get("history", [])  # [(role, text), ...]

    if not query:
        return jsonify({"error": "请输入查询内容"}), 400
    if len(query) > 500:
        return jsonify({"error": "查询内容过长，请精简到500字以内"}), 400

    # 检查缓存（只有无历史上下文时才用缓存，保证上下文追问不被缓存）
    if not history:
        cached = _cache_get(query, mode)
        if cached is not None:
            cached['suggestions'] = _generate_suggestions(query, cached, cached.get('aspect', 'general'))
            return jsonify(cached)

    # 构建上下文增强查询词
    context_query = query
    if history:
        # 从最近 3 轮历史中提取关键词增强查询
        recent_text = ' '.join([h.get('text', '') for h in history[-3:] if h.get('role') == 'user'])
        if recent_text:
            context_query = recent_text[-100:] + ' ' + query

    aspect = _detect_health_aspect(query)

    # 纯药品名识别：如果 query 本身匹配知识库中的药品，强制设为 medication
    is_pure_drug = False
    if aspect == 'general' and len(query) <= 15:
        matched_drugs = search.search_by_drug(query)
        if matched_drugs:
            aspect = 'medication'
            is_pure_drug = True

    # 如果有历史上下文且当前是追问，修正意图
    if history and aspect == 'general':
        last_assistant = ''
        for h in reversed(history):
            if h.get('role') == 'assistant':
                last_assistant = h.get('text', '')
                break
        # 如果上轮回复了疾病信息，当前追问很可能仍是该疾病相关
        disease_names_in_context = []
        for d_name in kb.diseases:
            if d_name in last_assistant:
                disease_names_in_context.append(d_name)
        if disease_names_in_context:
            # 用最近提到的疾病名增强查询
            context_query = ' '.join(disease_names_in_context[:2]) + ' ' + query

    result = {"query": query, "mode": mode, "aspect": aspect, "is_pure_drug": is_pure_drug}

    # ---- 疾病查询 ----
    if mode in ("auto", "disease"):
        diseases = search.search_disease(context_query)
        if not diseases:
            diseases = search.search_disease(query)
        if diseases:
            disease_results = []
            for name, sim, info in diseases:
                disease_results.append({
                    "name": info.get("name", ""),
                    "similarity": round(sim, 2),
                    "category": info.get("category", []),
                    "desc": info.get("desc", "")[:300],
                    "symptom": info.get("symptom", []),
                    "cause": info.get("cause", "")[:200],
                    "cure_department": info.get("cure_department", []),
                    "check": info.get("check", []),
                    "cure_way": info.get("cure_way", []),
                    "recommand_drug": info.get("recommand_drug", []),
                    "drug_detail": info.get("drug_detail", []),
                    "cured_prob": info.get("cured_prob", ""),
                    "cure_lasttime": info.get("cure_lasttime", ""),
                    "cost_money": info.get("cost_money", ""),
                    "prevent": info.get("prevent", "")[:300],
                    "acompany": info.get("acompany", []),
                    "get_prob": info.get("get_prob", ""),
                    "yibao_status": info.get("yibao_status", ""),
                })
            result["diseases"] = disease_results[:5]

    # ---- 症状查询 ----
    if mode in ("auto", "symptom"):
        symptoms = search.search_by_symptom(context_query)
        if not symptoms:
            symptoms = search.search_by_symptom(query)
        if symptoms:
            result["symptoms"] = [
                {
                    "disease": d_name,
                    "matched_symptom": sym,
                    "desc": kb.diseases.get(d_name, {}).get("desc", "")[:120],
                    "cure_department": kb.diseases.get(d_name, {}).get("cure_department", [])
                }
                for d_name, sym in symptoms[:10]
            ]

    # ---- 陪诊科室推荐 ----
    if mode in ("auto",):
        departments = search.search_department(query)
        if departments:
            result["departments"] = departments

    # ---- 药品查询 ----
    if mode in ("auto", "drug"):
        drugs = search.search_by_drug(query)
        if drugs:
            result["drugs"] = [
                {
                    "disease": d_name,
                    "matched_drug": dname,
                    "desc": kb.diseases.get(d_name, {}).get("desc", "")[:120]
                }
                for d_name, dname in drugs[:10]
            ]

    # ---- QA 查询（BM25 智能检索 + 意图扩展）----
    if mode in ("auto", "qa", "term"):
        # 先用上下文增强查询
        qa = search.search_qa(context_query, top_k=5)

        # 如果意图明确且 QA 结果少于 2 条，用扩展词再搜
        if aspect != 'general' and (not qa or len(qa) < 3):
            extended_query = query + ' ' + _aspect_question_map().get(aspect, '')
            qa = search.search_qa(extended_query, top_k=5)

        # 去重（按 answer 前 100 字符）
        seen_a = set()
        deduped_qa = []
        for q, a, s, score in qa:
            key = a[:100]
            if key not in seen_a:
                seen_a.add(key)
                deduped_qa.append((q, a, s, score))
        qa = deduped_qa

        if qa:
            result["qa"] = [
                {"question": q, "answer": a[:500], "source": s}
                for q, a, s, score in qa
            ]

    # ---- 术语搜索 ----
    if mode in ("auto", "term"):
        terms = search.search_all_terms(query)
        if terms:
            result["terms"] = terms[:15]

    # 判断是否有结果
    has_results = any(k in result for k in ["diseases", "symptoms", "drugs", "qa", "terms", "departments"])
    result["found"] = has_results

    # 实体识别
    result["entities"] = _extract_medical_entities(query)

    # 深度对话链：如果识别到疾病，自动构建多步引导
    if result["entities"]["diseases"] and result.get("diseases"):
        chain = _build_conversation_chain(result["entities"]["diseases"][0], result)
        if chain:
            result["conversation_chain"] = chain

    # 记录记忆
    _update_memory(session_id, 'user', query)

    # 写入缓存（无历史上下文的查询才能被缓存）
    if not history:
        _cache_set(query, mode, dict(result))

    # 生成智能追问建议
    result["suggestions"] = _generate_suggestions(query, result, aspect)

    return jsonify(result)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """聊天式接口 - 智能路由查询"""
    data = request.get_json()
    message = data.get("message", "").strip()

    if not message:
        return jsonify({"reply": "请输入您的问题。", "type": "error"})

    reply_parts = []

    # 1. 先尝试精确疾病匹配
    diseases = search.search_disease(message)
    if diseases:
        for name, sim, info in diseases[:3]:
            text = format_disease_response(info)
            reply_parts.append(text)

    # 2. 症状匹配
    symptoms = search.search_by_symptom(message)
    if symptoms and len(reply_parts) == 0:
        lines = ["", "▸ 症状关联疾病："]
        for d_name, sym in symptoms[:5]:
            desc = kb.diseases.get(d_name, {}).get("desc", "")[:80]
            lines.append(f"  ● {d_name}（匹配症状：{sym}）")
            if desc:
                lines.append(f"    {desc}")
        reply_parts.append("\n".join(lines))

    # 3. 药品匹配
    drugs = search.search_by_drug(message)
    if drugs and len(reply_parts) == 0:
        lines = ["", "▸ 药品关联疾病："]
        for d_name, dname in drugs[:5]:
            desc = kb.diseases.get(d_name, {}).get("desc", "")[:80]
            lines.append(f"  ● {d_name}（匹配药品：{dname}）")
            if desc:
                lines.append(f"    {desc}")
        reply_parts.append("\n".join(lines))

    # 4. QA 问答
    qa = search.search_qa(message, top_k=3)
    if qa and len(reply_parts) == 0:
        for i, (q, a, source, _) in enumerate(qa, 1):
            reply_parts.append(f"▸ 相关问答 [{i}]\n问：{q[:200]}\n答：{a[:500]}")

    # 5. 如果没有任何匹配
    if not reply_parts:
        terms = search.search_all_terms(message)
        if terms:
            reply_parts.append(f"未找到精确匹配。相关术语：{'、'.join(terms[:20])}")
        else:
            reply_parts.append(
                "抱歉，在知识库中未找到相关信息。\n\n"
                "建议：\n"
                "  • 尝试输入具体的疾病名称（如\"糖尿病\"）\n"
                "  • 尝试输入症状（如\"头痛\"）\n"
                "  • 尝试输入药品名称（如\"二甲双胍\"）\n"
                "  • 尝试输入医学问题"
            )

    reply = "\n\n".join(reply_parts)
    return jsonify({
        "reply": reply,
        "type": "medical",
        "found": len(reply_parts) > 0 and "抱歉" not in reply_parts[0]
    })


@app.route("/api/sim-response", methods=["POST"])
def api_sim_response():
    """陪诊模拟智能回复 — 深度融合知识库 + 对话状态追踪"""
    data = request.get_json()
    user_msg = data.get("message", "").strip()
    patient = data.get("patient", {})  # {name, age, sex, dept, scenario, stage}
    session_id = data.get("session_id", "sim_default")

    if not user_msg:
        return jsonify({"reply": "（患者看着你，等你说话……）", "stage": patient.get("stage", 0)})

    p_name = patient.get("name", "患者")
    p_age = patient.get("age", 50)
    p_sex = patient.get("sex", "女")
    p_dept = patient.get("dept", "")
    p_scenario = patient.get("scenario", "")
    p_stage = patient.get("stage", 0)

    # 1. 分析用户意图
    q = user_msg.lower()
    intent = _detect_sim_intent(q)
    new_stage = _detect_stage_advance(q, p_stage)

    # 2. 搜索知识库 — 多层次检索
    # 2a. 搜索 QA
    kb_qa = search.search_qa(user_msg, top_k=5)
    kb_context = ""
    if kb_qa:
        relevant = []
        for _, answer, source, _ in kb_qa:
            if "peizhen" in source and len(relevant) < 3:
                relevant.append(answer[:300])
            elif len(relevant) < 3:
                relevant.append(answer[:200])
        if relevant:
            kb_context = " ".join(relevant)

    # 2b. 搜索疾病信息（用科室 + 用户消息双路搜索）
    disease_info = ""
    if p_dept:
        diseases = search.search_disease(p_dept)
        if diseases:
            disease_info = diseases[0][2].get("desc", "")[:150]
    if not disease_info:
        diseases = search.search_disease(user_msg)
        if diseases:
            disease_info = diseases[0][2].get("desc", "")[:150]

    # 2c. 获取用药信息（pharmacy 意图时特别重要）
    drug_context = ""
    if intent in ('pharmacy', 'medication'):
        drugs = search.search_by_drug(user_msg)
        if drugs:
            drug_info_list = []
            for d_name, dname in drugs[:3]:
                info = kb.diseases.get(d_name, {})
                drug_detail = info.get('drug_detail', [])
                if drug_detail:
                    drug_info_list.append('、'.join(str(dd) for dd in drug_detail[:3]))
            if drug_info_list:
                drug_context = '；'.join(drug_info_list)[:200]

    # 3. 记录对话历史
    _update_memory(session_id, 'user', user_msg)

    # 4. 生成患者回复
    reply = _generate_patient_reply(
        user_msg=user_msg,
        intent=intent,
        patient_name=p_name,
        patient_age=p_age,
        patient_sex=p_sex,
        patient_dept=p_dept,
        patient_scenario=p_scenario,
        stage=p_stage,
        new_stage=new_stage,
        kb_context=kb_context,
        disease_info=disease_info
    )

    # 如果涉及用药，追加药品知识提示
    if drug_context and intent == 'pharmacy':
        reply += f'\n（📋 知识库用药参考：{drug_context[:150]}）'

    _update_memory(session_id, 'assistant', reply)

    return jsonify({
        "reply": reply,
        "stage": new_stage,
        "intent": intent,
        "kb_referenced": bool(kb_context or drug_context)
    })


def _detect_sim_intent(query):
    """检测用户（陪诊师）的意图类别 — 更精确的意图优先匹配"""
    q = query.lower()
    # greet / leave 是最独立的两端，优先判断
    if any(w in q for w in ['你好', '您好', '我是', '陪诊', '放心', '别担心', '没事', '会帮']):
        return 'greet'
    if any(w in q for w in ['结束', '完成', '谢谢', '感谢', '回去', '再见', '下次', '走了', '离开', '总结']):
        return 'leave'
    # 流程阶段：register → navigate → wait → consult → payment → pharmacy
    if any(w in q for w in ['挂号', '挂哪', '挂什么', '取号', '自助机', '预约', '窗口', '专家号', '普通号']):
        return 'register'
    if any(w in q for w in ['在哪', '几楼', '怎么走', '电梯', '楼梯', '左转', '右转', '前面', '这边', '跟我']):
        return 'navigate'
    if any(w in q for w in ['等一下', '等一会', '稍等', '马上', '快了', '前面还有', '叫号', '排队']):
        return 'wait'
    # pharmacy 在 consult 之前：用药相关问题更精确（取药/怎么吃/副作用）
    if any(w in q for w in ['取药', '药房', '吃药', '怎么吃', '副作用', '用法', '用量', '处方', '药盒']):
        return 'pharmacy'
    if any(w in q for w in ['医生', '检查', '诊断', '严重', '报告', '结果', '治疗', '手术', '开药']):
        return 'consult'
    if any(w in q for w in ['缴费', '多少钱', '费用', '医保', '报销', '付款', '支付', '检查项目', '化验', '抽血', 'CT', 'B超', '心电图']):
        return 'payment'
    return 'general'


def _detect_stage_advance(query, current_stage):
    """检测就诊阶段是否推进"""
    q = query.lower()
    advances = [
        (['挂好', '挂完', '号拿到', '挂号成功', '取到号', '挂上号', '挂好了'], 2),
        (['到了', '就是这', '候诊', '等.*区', '诊室.*门口'], 3),
        (['叫到', '轮到', '到.*我们', '进去', '进.*诊室'], 4),
        (['看完', '医生.*说', '诊断.*出来', '开.*药', '开.*检查', '出来.*了'], 5),
        (['缴完', '付完', '交完', '检查.*做', '抽.*完', '做.*完'], 6),
        (['拿.*药', '取.*药', '药.*拿到', '药.*好'], 7),
    ]
    for patterns, next_stage in advances:
        if any(re.search(p, q) for p in patterns):
            if next_stage > current_stage:
                return next_stage
    return current_stage


def _generate_suggestions(query, result, aspect):
    """根据当前查询和结果生成智能追问建议"""
    suggestions = []

    diseases = result.get('diseases', [])
    first_disease = diseases[0] if diseases else None
    d_name = first_disease.get('name', '') if first_disease else ''

    if d_name:
        suggestions.append(f"{d_name}的饮食需要注意什么？")
        suggestions.append(f"{d_name}用什么药治疗？")
        suggestions.append(f"{d_name}怎么预防？")
        if first_disease.get('symptom'):
            suggestions.append(f"{d_name}有哪些早期症状？")
        if first_disease.get('cure_department'):
            dept = first_disease['cure_department'][0] if first_disease['cure_department'] else ''
            if dept:
                suggestions.append(f"去{dept}就诊要准备什么？")
    else:
        # 没有找到疾病，根据意图和查询生成通用建议
        if aspect == 'diet':
            suggestions = ['这个病有什么饮食禁忌？', '吃什么有助于康复？', '需要补充哪些营养？']
        elif aspect == 'medication':
            suggestions = ['这个药有什么副作用？', '饭前吃还是饭后吃？', '忘记吃药了怎么办？']
        elif aspect == 'exercise':
            suggestions = ['每天运动多久合适？', '什么运动方式比较好？', '运动时要注意什么？']
        elif aspect == 'prevention':
            suggestions = ['怎么预防复发？', '有哪些危险因素？', '需要定期做什么检查？']
        else:
            suggestions = [
                f'关于"{query[:15]}"有什么需要注意的？',
                f'{query[:15]}怎么治疗？' if len(query) > 2 else '这个病怎么治疗？',
                '需要挂什么科室？',
            ]

    # 去重并取前 3 个
    seen = set()
    unique = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique[:3]


def _generate_patient_reply(user_msg, intent, patient_name, patient_age, patient_sex,
                             patient_dept, patient_scenario, stage, new_stage,
                             kb_context, disease_info):
    """生成患者口吻的自然回复 — 深度融合知识库"""

    # 根据意图构建回复骨架
    templates = {
        'greet': [
            f'（{patient_name}抬头看你）你是陪我看病的吗？太好了，我这正愁不知道怎么办呢……',
            f'（{patient_name}勉强笑了笑）谢谢你啊，有个人陪着我就踏实多了。我这{patient_dept}的病，一直想来看又不敢自己来。',
            f'（{patient_name}点点头）好好好，今天就麻烦你了。我这腿脚不太方便，走路慢，你别嫌我慢啊。',
        ],
        'register': [
            f'（{patient_name}掏医保卡）这卡怎么用啊？是插那个机器里吗？我不会弄这些……',
            f'（{patient_name}有点急）挂号要多少钱？我没带太多现金，手机支付也不太会弄。',
            f'（{patient_name}看着自助机发愣）这屏幕上的字我看不太清，{patient_dept}在哪个科室啊？',
            f'（{patient_name}犹豫）专家号和普通号有啥区别？我这情况需要挂专家吗？',
        ],
        'navigate': [
            f'（{patient_name}跟着你走）这医院太大了，{patient_dept}在几楼啊？',
            f'（{patient_name}有点喘）慢点走啊，我这腿走不快。有电梯吗？',
            f'（{patient_name}四处张望）那些牌子我都看不太懂，你帮我看看往哪边走？',
        ],
        'wait': [
            f'（{patient_name}坐下后有点不安）怎么还没叫到我？前面还有几个人啊？',
            f'（{patient_name}小声问）待会见医生我该怎么说？我怕一紧张就说不清楚。',
            f'（{patient_name}看看手表）等了挺久了，不会错过了吧？',
        ],
        'consult': [
            f'（{patient_name}进诊室后紧张）医生你好……我这{patient_dept}的毛病，最近老不舒服……',
            f'（{patient_name}转头小声问你）医生说的这个检查是什么意思？我没听明白……',
            f'（{patient_name}担心地问）医生，这严不严重？要不要住院啊？',
        ],
        'payment': [
            f'（{patient_name}拿着单子）这些检查要多少钱？医保能报多少？',
            f'（{patient_name}站在缴费窗口前）人太多了，我这老腿站不了太久……',
            f'（{patient_name}算了算）今天带的钱够不够啊……',
        ],
        'pharmacy': [
            f'（{patient_name}看着药盒）这药一天吃几次？饭前还是饭后？我怕吃错了。',
            f'（{patient_name}问）这药有副作用吗？我胃不好，能吃吗？',
            f'（{patient_name}记性不好）你帮我写一下怎么吃，我怕回去就忘了。',
        ],
        'leave': [
            f'（{patient_name}感激地）今天真是太谢谢你了！要不是你陪着，我这老骨头真不知道怎么办。',
            f'（{patient_name}有点担心）下次复查我还得自己来，你能再陪我吗？怎么预约你啊？',
            f'（{patient_name}临走前）你帮我记的那些，能再给我说一遍吗？我怕忘了。',
        ],
        'general': [
            f'（{patient_name}看着你）嗯，你说接下来该怎么办？',
            f'（{patient_name}点点头）好的，我听你的安排。',
            f'（{patient_name}有点茫然）这医院流程太多了，你帮我多操操心啊。',
        ],
    }

    replies = templates.get(intent, templates['general'])

    # 深度融合知识库内容
    if kb_context:
        kb_sentences = [s.strip() for s in kb_context.replace('\n', '。').split('。')
                       if len(s.strip()) > 5]
        if kb_sentences and random.random() < 0.55:  # 55% 概率融入知识（从 40% 提升）
            kb_hint = kb_sentences[:2]
            # 根据意图选择融入方式
            if intent in ('pharmacy', 'medication'):
                extra = (f'\n（{patient_name}听完你的用药解释后，似懂非懂地点点头）'
                        f'哦，{"".join(kb_hint[:1])[:100]}……那我按你说的吃。')
            elif intent in ('consult',):
                extra = (f'\n（{patient_name}若有所思）'
                        f'原来是这样……{"".join(kb_hint[:1])[:80]}，那我放心多了。')
            else:
                extra = (f'\n（{patient_name}听了你的解释后说）'
                        f'哦，{"".join(kb_hint[:1])[:100]}……是这样啊，那我明白了。')
            replies = [r + extra for r in replies]

    # 融入疾病信息
    if disease_info and random.random() < 0.35:
        snippet = disease_info[:80]
        extra = (f'\n（{patient_name}突然想起什么）'
                f'对了，我听说{snippet}……这个跟我这病有关系吗？')
        replies = [r + extra for r in replies]

    # 如果阶段推进，追加阶段转换语
    stage_transitions = {
        2: f'\n📍（已到挂号窗口，准备挂号）',
        3: f'\n📍（已到{patient_dept}科室门口，进入候诊区）',
        4: f'\n📍（叫号系统响起，轮到{patient_name}了）',
        5: f'\n📍（就诊结束，拿着医生开的单子走出诊室）',
        6: f'\n📍（缴费/检查完成，准备取药）',
        7: f'\n📍（取完药，准备离院）',
    }
    if new_stage > stage and new_stage in stage_transitions:
        reply = random.choice(replies)
        reply += stage_transitions[new_stage]
        return reply

    return random.choice(replies)


@app.route("/api/suggest", methods=["POST"])
def api_suggest():
    """智能追问建议接口"""
    data = request.get_json()
    query = data.get("query", "").strip()
    context = data.get("context", {})  # 当前搜索结果或对话上下文

    if not query:
        return jsonify({"suggestions": []})

    aspect = _detect_health_aspect(query)
    suggestions = _generate_suggestions(query, context, aspect)
    return jsonify({"suggestions": suggestions})


@app.route("/api/drug-check", methods=["POST"])
def api_drug_check():
    """药品相互作用检查 — 输入多个药品名，检查知识库中是否有相关警告"""
    data = request.get_json()
    drug_names = data.get("drugs", [])  # ["二甲双胍", "阿司匹林"]

    if not drug_names or len(drug_names) < 2:
        return jsonify({"warning": None, "message": "请输入至少两种药品名进行比较"})

    results = []
    for dname in drug_names:
        dname = dname.strip()
        if not dname:
            continue
        related = search.search_by_drug(dname)
        if related:
            diseases = list(set(d_name for d_name, _ in related[:5]))
            results.append({
                "drug": dname,
                "found": True,
                "related_diseases": diseases,
                "warning": "请咨询医生确认是否存在药物相互作用" if len(diseases) > 1 else None
            })
        else:
            results.append({"drug": dname, "found": False})

    # 检查是否有共同治疗的疾病（可能相互作用）
    if len(results) >= 2:
        all_diseases = [set(r.get('related_diseases', [])) for r in results if r.get('found')]
        if len(all_diseases) >= 2:
            common = all_diseases[0].intersection(*all_diseases[1:])
            if common:
                return jsonify({
                    "warning": f"这些药品可能共同作用于: {'、'.join(list(common)[:5])}",
                    "advice": "请务必咨询医生或药师，确认药品间相互作用",
                    "drugs": results,
                    "shared_diseases": list(common)
                })

    return jsonify({
        "warning": None,
        "drugs": results,
        "message": "未检测到已知的相互作用，但仍建议咨询专业药师"
    })


@app.route("/api/health-tips", methods=["GET"])
def api_health_tips():
    """每日健康小贴士 — 从知识库随机生成"""
    tips = [
        {"title": "💧 饮水提醒", "content": "每天饮用 1500-2000ml 水，少量多次，不要等口渴再喝。水肿、心肾功能不全者需遵医嘱控制饮水量。"},
        {"title": "🏃 运动建议", "content": "每周至少 150 分钟中等强度有氧运动，如快走、游泳、骑车。运动前热身 5-10 分钟，避免运动损伤。"},
        {"title": "😴 睡眠贴士", "content": "成年人每日应保证 7-8 小时睡眠。固定作息、睡前避免手机蓝光、卧室温度 18-22℃ 有助于睡眠质量。"},
        {"title": "🍎 饮食口诀", "content": "每天一斤蔬菜半斤水果，谷物粗细搭配，肉类优先选择鱼禽，少盐少油控糖（盐 < 6g/天，油 25-30g/天）。"},
        {"title": "💊 用药安全", "content": "服药请用温水送服，勿用茶水、牛奶、果汁。不要自行增减药量或停药。过期药品请投入有害垃圾桶。"},
        {"title": "🧠 心理健康", "content": "焦虑或失眠持续 2 周以上，建议寻求专业心理帮助。每天给自己 10 分钟正念呼吸，有助于缓解压力。"},
        {"title": "🦷 口腔健康", "content": "每天刷牙 2 次（每次不少于 2 分钟），使用含氟牙膏，每半年到一年洗牙一次。牙周炎与心血管疾病相关。"},
        {"title": "👀 用眼卫生", "content": "遵循 20-20-20 法则：每看屏幕 20 分钟，向 20 英尺（约 6 米）外远眺 20 秒。保持屏幕距离 50-70cm。"},
        {"title": "🤰 孕期提醒", "content": "备孕及孕早期每日补充叶酸 0.4mg，按时产检，避免接触有害物质。孕期适当运动有助于顺利分娩。"},
        {"title": "👴 老年防跌倒", "content": "65 岁以上老人家中应安装扶手、保持地面干燥、夜间留夜灯。跌倒后即使无明显外伤也应就医检查。"},
        {"title": "🌡 血压监测", "content": "家庭自测血压应在安静状态下进行，测前 30 分钟禁烟、咖啡。测量时背靠椅背、双脚平放、手臂与心脏同高。"},
        {"title": "🍬 血糖管理", "content": "空腹血糖正常值: 3.9-6.1 mmol/L。糖尿病患者应定期监测糖化血红蛋白（HbA1c），控制目标一般 < 7%。"},
    ]

    # 偶尔从知识库中提取真实预防建议
    if random.random() < 0.3 and kb.diseases:
        d_name = random.choice(list(kb.diseases.keys()))
        info = kb.diseases[d_name]
        prevent = info.get('prevent', '')
        if prevent and len(prevent) > 20:
            tips.append({
                "title": f"🩺 {d_name}预防",
                "content": prevent[:200]
            })

    tip = random.choice(tips)
    tip['cached_at'] = int(time.time())
    return jsonify(tip)


@app.route("/api/search-suggest", methods=["GET"])
def api_search_suggest():
    """快速自动补全 — 只搜疾病名，轻量级"""
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify({"suggestions": []})

    results = []
    # 精确前缀匹配优先
    for name in kb.diseases:
        if name.startswith(q) and len(results) < 8:
            info = kb.diseases[name]
            results.append({
                "name": name,
                "category": info.get("category", [])[:2],
                "desc": info.get("desc", "")[:60]
            })

    # 不足则补充模糊匹配
    if len(results) < 5:
        fuzzy = search.fuzzy_match(q, kb.disease_index, top_k=8, threshold=0.25)
        for name, sim, info in fuzzy:
            if not any(r['name'] == name for r in results):
                results.append({
                    "name": name,
                    "similarity": round(sim, 2),
                    "desc": (info[1] if isinstance(info, tuple) else '')[:60]
                })
                if len(results) >= 8:
                    break

    return jsonify({"suggestions": results[:8]})


def _synthesize_answer(query, disease_info, qa_results, aspect='general'):
    """将多条 QA 结果合成为一段连贯的自然语言回答"""
    if not qa_results and not disease_info:
        return None

    parts = []

    # 1. 疾病概述（如果有）
    if disease_info:
        d_name = disease_info.get('name', '')
        d_desc = disease_info.get('desc', '')
        d_prevent = disease_info.get('prevent', '')
        d_symptoms = disease_info.get('symptom', [])
        d_dept = disease_info.get('cure_department', [])
        d_drugs = disease_info.get('recommand_drug', [])

        if d_name:
            parts.append(f'根据您的问题，为您介绍「{d_name}」的相关信息：')

        if d_desc and d_desc.strip():
            parts.append(f'📝 {d_desc[:200]}')

        if d_symptoms and len(d_symptoms) > 0:
            parts.append(f'🤒 常见症状包括：{"、".join(d_symptoms[:8])}。')

        if d_dept and len(d_dept) > 0:
            parts.append(f'🏥 建议就诊科室：{"、".join(d_dept[:3])}。')

        if d_drugs and len(d_drugs) > 0 and aspect in ('medication', 'general'):
            parts.append(f'💊 常用药物：{"、".join(d_drugs[:5])}。')

        if d_prevent and d_prevent.strip():
            parts.append(f'🛡 预防建议：{d_prevent[:200]}')

    # 2. QA 知识补充
    if qa_results:
        if disease_info:
            parts.append('📚 相关知识问答：')
        seen_answers = set()
        for q, a, _source, _score in qa_results[:3]:
            key = a[:80]
            if key in seen_answers:
                continue
            seen_answers.add(key)
            short_q = q[:80] + ('...' if len(q) > 80 else '')
            short_a = a[:250] + ('...' if len(a) > 250 else '')
            parts.append(f'❓ {short_q}\n💬 {short_a}')

    # 3. 通用结尾建议
    if aspect == 'diet':
        parts.append('💡 饮食调理应配合药物治疗，建议咨询营养师制定个性化方案。')
    elif aspect == 'medication':
        parts.append('⚠ 以上药物信息仅供参考，具体用药请遵医嘱，不可自行调整剂量。')
    elif aspect == 'prevention':
        parts.append('💡 定期体检和健康生活方式是预防疾病的关键。')
    elif aspect == 'daily_care':
        parts.append('💡 日常护理需持之以恒，建议家属共同参与，定期复诊评估效果。')
    else:
        parts.append('⚠ 以上信息来自医学知识库，仅供参考，不能替代专业医疗诊断。如有不适请及时就医。')

    return '\n\n'.join(parts)


@app.route("/api/answer", methods=["POST"])
def api_answer():
    """智能回答 — 将搜索结果合成为自然语言回答"""
    data = request.get_json()
    query = data.get("query", "").strip()
    session_id = data.get("session_id", "default")

    if not query:
        return jsonify({"error": "请输入问题"}), 400

    aspect = _detect_health_aspect(query)

    # 搜索疾病
    diseases = search.search_disease(query)
    disease_info = None
    if diseases:
        info = diseases[0][2]
        disease_info = {
            'name': info.get('name', ''),
            'desc': info.get('desc', ''),
            'symptom': info.get('symptom', []),
            'cure_department': info.get('cure_department', []),
            'recommand_drug': info.get('recommand_drug', []),
            'prevent': info.get('prevent', ''),
        }

    # 搜索 QA
    qa = search.search_qa(query, top_k=5)
    # 意图扩展
    if aspect != 'general' and (not qa or len(qa) < 3):
        extended = query + ' ' + _aspect_question_map().get(aspect, '')
        qa = search.search_qa(extended, top_k=5)

    # 合成回答
    answer = _synthesize_answer(query, disease_info, qa, aspect)

    if not answer:
        answer = ('抱歉，在知识库中未找到与「' + query + '」直接相关的信息。\n\n'
                  '建议：\n'
                  '• 尝试输入具体的疾病名称（如"糖尿病"）\n'
                  '• 描述具体症状（如"头痛发热"）\n'
                  '• 输入药品名称（如"二甲双胍"）')

    _update_memory(session_id, 'user', query)
    _update_memory(session_id, 'assistant', answer[:500])

    suggestions = _generate_suggestions(query, {'diseases': [disease_info] if disease_info else []}, aspect)

    return jsonify({
        'answer': answer,
        'aspect': aspect,
        'found': disease_info is not None or len(qa) > 0,
        'suggestions': suggestions
    })


@app.route("/api/departments", methods=["GET"])
def api_departments():
    """返回所有科室列表及关联疾病数"""
    dept_list = []
    for dept, diseases in kb.dept_map.items():
        dept_list.append({
            "name": dept,
            "disease_count": len(diseases),
            "top_diseases": diseases[:3]
        })
    dept_list.sort(key=lambda x: -x['disease_count'])
    return jsonify({"departments": dept_list[:30]})


def _build_conversation_chain(disease_name, search_result):
    """为疾病构建深度对话链：概述→症状→病因→治疗→预防→追问"""
    diseases = search_result.get('diseases', [])
    if not diseases:
        return None

    d = diseases[0]
    chain = {
        'disease': disease_name,
        'steps': []
    }

    # Step 1: 疾病概述
    if d.get('desc'):
        chain['steps'].append({
            'icon': '📝',
            'title': '疾病概述',
            'content': d['desc'][:250],
            'question': f'{disease_name}的早期症状有哪些？'
        })

    # Step 2: 常见症状
    if d.get('symptom'):
        chain['steps'].append({
            'icon': '🤒',
            'title': '常见症状',
            'content': '、'.join(d['symptom'][:8]),
            'question': f'{disease_name}出现这些症状怎么办？'
        })

    # Step 3: 病因
    if d.get('cause'):
        chain['steps'].append({
            'icon': '🔬',
            'title': '主要病因',
            'content': d['cause'][:200],
            'question': f'如何预防{disease_name}的发生？'
        })

    # Step 4: 就诊科室
    if d.get('cure_department'):
        chain['steps'].append({
            'icon': '🏥',
            'title': '就诊科室',
            'content': '、'.join(d['cure_department'][:3]),
            'question': f'去{"、".join(d["cure_department"][:1])}就诊需要准备什么？'
        })

    # Step 5: 预防措施
    if d.get('prevent'):
        chain['steps'].append({
            'icon': '🛡',
            'title': '预防措施',
            'content': d['prevent'][:200],
            'question': f'{disease_name}患者日常需要注意什么？'
        })

    # Step 6: 推荐药品
    if d.get('recommand_drug'):
        chain['steps'].append({
            'icon': '💊',
            'title': '常用药物',
            'content': '、'.join(d['recommand_drug'][:5]),
            'question': f'{disease_name}用药有什么注意事项？'
        })

    if chain['steps']:
        chain['has_chain'] = True
        return chain
    return None


def _extract_medical_entities(query):
    """基于字典的医疗命名实体识别 — 从查询中提取疾病、症状、药品、科室

    性能：限制每个类别扫描上限，避免超长查询导致过慢
    """
    entities = {'diseases': [], 'symptoms': [], 'drugs': [], 'departments': []}

    # 疾病匹配 — 扫描全部 8815 个疾病名（每次 O(N) 但 N=8815，单次 < 1ms）
    for d_name in _DISEASES_BY_LENGTH_DESC:
        if len(d_name) >= 3 and d_name in query:
            entities['diseases'].append(d_name)
            break

    # 症状匹配（只匹配长度 >= 2 的症状，限 2000 次）
    scanned = 0
    for sym in kb.symptom_map:
        if scanned >= 2000:
            break
        if len(sym) >= 2 and sym in query and sym not in entities['diseases']:
            entities['symptoms'].append(sym)
            if len(entities['symptoms']) >= 5:
                break
        scanned += 1

    # 药品匹配（限 3000 次）
    scanned = 0
    for drug in kb.drug_map:
        if scanned >= 3000:
            break
        if len(drug) >= 2 and drug in query:
            entities['drugs'].append(drug)
            if len(entities['drugs']) >= 3:
                break
        scanned += 1

    # 科室匹配（全部，数量少 59 个）
    for dept in kb.dept_map:
        if len(dept) >= 2 and dept in query:
            entities['departments'].append(dept)

    entities['has_entities'] = any(entities.values())
    return entities


@app.route("/api/stream", methods=["POST"])
def api_stream():
    """SSE 流式回答 — 模拟豆包逐字输出，每次推送一个句子"""
    data = request.get_json()
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"error": "请输入问题"}), 400

    def generate():
        import time as _time
        try:
            # 搜索
            diseases = search.search_disease(query)
            disease_info = None
            if diseases:
                info = diseases[0][2]
                disease_info = {
                    'name': info.get('name', ''),
                    'desc': info.get('desc', ''),
                    'symptom': info.get('symptom', []),
                    'cure_department': info.get('cure_department', []),
                    'recommand_drug': info.get('recommand_drug', []),
                    'prevent': info.get('prevent', ''),
                    'cause': info.get('cause', ''),
                    'check': info.get('check', []),
                    'cure_way': info.get('cure_way', []),
                }

            qa = search.search_qa(query, top_k=5)

            # 构建回答
            answer = _synthesize_answer(query, disease_info, qa,
                                         _detect_health_aspect(query))
            if not answer:
                answer = '抱歉，在知识库中未找到相关信息。请尝试更具体的描述。'

            # 按句子切分，逐句发送
            sentences = re.split(r'(?<=[。！？\n])', answer)
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                yield f"data: {json.dumps({'chunk': sent, 'done': False}, ensure_ascii=False)}\n\n"
                _time.sleep(0.08)  # 模拟思考时间

            # 发送追问建议
            suggestions = _generate_suggestions(query,
                {'diseases': [disease_info] if disease_info else []},
                _detect_health_aspect(query))
            yield f"data: {json.dumps({'chunk': '', 'done': True, 'suggestions': suggestions}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'chunk': f'抱歉，处理您的问题时出现了错误：{str(e)[:100]}', 'done': True, 'suggestions': []}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    """搜索反馈收集 — 记录用户对搜索结果的满意度"""
    data = request.get_json()
    query = data.get("query", "")
    rating = data.get("rating", "")  # "good" | "bad"
    session_id = data.get("session_id", "anon")

    # 简单日志记录（生产环境应写入数据库）
    print(f"[反馈] session={session_id} query={query[:50]} rating={rating}")

    return jsonify({"status": "ok", "message": "感谢反馈！"})


@app.route("/api/compare", methods=["POST"])
def api_compare():
    """疾病对比 — 输入两个疾病名，返回结构化对比"""
    data = request.get_json()
    name1 = data.get("disease1", "").strip()
    name2 = data.get("disease2", "").strip()

    if not name1 or not name2:
        return jsonify({"error": "请输入两个疾病名"}), 400

    def get_disease_info(name):
        """精确匹配或模糊匹配疾病"""
        if name in kb.diseases:
            return kb.diseases[name]
        results = search.search_disease(name)
        if results:
            return results[0][2]
        return None

    d1 = get_disease_info(name1)
    d2 = get_disease_info(name2)

    if not d1 and not d2:
        return jsonify({"error": f"未找到「{name1}」和「{name2}」", "found": False})

    comparison = {"found": True}

    for label, d, dname in [("disease1", d1, name1), ("disease2", d2, name2)]:
        if d:
            comparison[label] = {
                "name": d.get("name", dname),
                "matched": d.get("name", "") == dname,
                "desc": d.get("desc", "")[:200],
                "category": d.get("category", []),
                "symptom": d.get("symptom", [])[:10],
                "cause": d.get("cause", "")[:150],
                "cure_department": d.get("cure_department", []),
                "cure_way": d.get("cure_way", []),
                "prevent": d.get("prevent", "")[:200],
                "cure_lasttime": d.get("cure_lasttime", ""),
                "cured_prob": d.get("cured_prob", ""),
            }
        else:
            comparison[label] = {"name": dname, "found": False}

    # 计算相似项和差异项
    if d1 and d2:
        s1 = set(d1.get("symptom", []))
        s2 = set(d2.get("symptom", []))
        comparison["common_symptoms"] = list(s1 & s2)[:10]
        comparison["unique_symptoms_1"] = list(s1 - s2)[:10]
        comparison["unique_symptoms_2"] = list(s2 - s1)[:10]

        dept1 = set(d1.get("cure_department", []))
        dept2 = set(d2.get("cure_department", []))
        comparison["common_departments"] = list(dept1 & dept2)

    return jsonify(comparison)


if __name__ == "__main__":
    init_kb()
    print("\n" + "=" * 60)
    print("  陪优佳 Web 服务已启动")
    print("  访问: http://localhost:5000")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
