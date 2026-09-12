#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
陪优佳检索系统
Medical Terminology Knowledge Base Search System

基于已下载的医疗数据集构建：
- DiseaseKG (疾病知识图谱)
- HuatuoGPT-sft (华佗医疗问答)
- huatuo_knowledge_graph_qa (知识图谱QA)
- ShenNong_TCM (中医对话)
- ChatMed_Consult (医疗问诊)
- Chinese-medical-dialogue (医疗对话)
- SoulChatCorpus (心理健康)
- CareGPT-YL (药品+导诊)

用法:
    python med_term_kb.py search "糖尿病"
    python med_term_kb.py disease "2型糖尿病"
    python med_term_kb.py symptom "头痛 发热"
    python med_term_kb.py drug "二甲双胍"
    python med_term_kb.py interactive
"""

import json
import math
import os
import re
import sys
from collections import defaultdict, Counter
from difflib import SequenceMatcher

try:
    import jieba
    jieba.setLogLevel(20)  # suppress debug output during tokenization
    _JIEBA_AVAILABLE = True
except ImportError:
    _JIEBA_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ═══════════════════════════════════════════════════════════
# 1. 数据加载层
# ═══════════════════════════════════════════════════════════

class MedicalKnowledgeBase:
    """统一医疗知识库"""

    def __init__(self, base_dir=BASE_DIR):
        self.base_dir = base_dir
        self.diseases = {}          # name -> disease info
        self.disease_index = []     # [(name, desc, category), ...] for search
        self.symptom_map = defaultdict(list)  # symptom -> [disease names]
        self.drug_map = defaultdict(list)     # drug -> [disease names]
        self.dept_map = defaultdict(list)     # department -> [disease names]
        self.qa_pairs = []          # [(question, answer, source), ...]
        self.term_dict = set()      # all unique medical terms
        self._loaded = False

    def load_all(self):
        """加载所有数据集"""
        print("=" * 60)
        print("  加载医疗知识库...")
        print("=" * 60)
        self._load_disease_kg()
        self._load_synthetic_diseases()
        self._load_huatuo_kg_qa()
        self._load_huatuo_sft()
        self._load_shennong_tcm()
        self._load_chatmed_consult()
        self._load_chinese_medical_dialogue()
        self._load_synthetic_qa()
        self._load_peizhen_exam_kb()
        self._build_term_index()
        self._build_qa_index()
        self._loaded = True
        self._print_stats()

    def _load_disease_kg(self):
        """加载 DiseaseKG 疾病知识图谱 (最核心的结构化数据)"""
        path = f"{self.base_dir}/DiseaseKG-CN/medical.json"
        if not os.path.exists(path):
            print(f"  [WARN] DiseaseKG not found: {path}")
            return
        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    name = d.get("name", "")
                    if not name:
                        continue
                    self.diseases[name] = {
                        "name": name,
                        "desc": d.get("desc", ""),
                        "category": d.get("category", []),
                        "symptom": d.get("symptom", []),
                        "cause": d.get("cause", ""),
                        "prevent": d.get("prevent", ""),
                        "cure_way": d.get("cure_way", []),
                        "cure_department": d.get("cure_department", []),
                        "cure_lasttime": d.get("cure_lasttime", ""),
                        "cured_prob": d.get("cured_prob", ""),
                        "check": d.get("check", []),
                        "recommand_drug": d.get("recommand_drug", []),
                        "drug_detail": d.get("drug_detail", []),
                        "cost_money": d.get("cost_money", ""),
                        "acompany": d.get("acompany", []),
                        "get_prob": d.get("get_prob", ""),
                        "get_way": d.get("get_way", ""),
                        "yibao_status": d.get("yibao_status", ""),
                    }
                    # 建立各类索引
                    for s in d.get("symptom", []):
                        self.symptom_map[s].append(name)
                    # drug_detail is list of strings: "药品名(别称)"
                    for drug_str in d.get("drug_detail", []):
                        if isinstance(drug_str, str):
                            # Extract drug name before first paren
                            drug_name = drug_str.split("(")[0].strip()
                            if drug_name and len(drug_name) < 30:
                                self.drug_map[drug_name].append(name)
                    for drug_str in d.get("recommand_drug", []):
                        if isinstance(drug_str, str):
                            drug_name = drug_str.split("(")[0].strip()
                            if drug_name and len(drug_name) < 30:
                                self.drug_map[drug_name].append(name)
                    for dept in d.get("cure_department", []):
                        self.dept_map[dept].append(name)
                    # 收集术语
                    self.term_dict.add(name)
                    for cat in d.get("category", []):
                        self.term_dict.add(cat)
                    count += 1
                except json.JSONDecodeError:
                    pass
        self.disease_index = [
            (name, info["desc"][:100], info["category"])
            for name, info in self.diseases.items()
        ]
        print(f"  [OK] DiseaseKG: {count} 种疾病, "
              f"{len(self.symptom_map)} 种症状, "
              f"{len(self.drug_map)} 种药品")

    def _load_huatuo_kg_qa(self):
        """加载华佗知识图谱QA"""
        path = f"{self.base_dir}/huatuo_knowledge_graph_qa/train_datasets.jsonl"
        if not os.path.exists(path):
            print(f"  [WARN] huatuo knowledge graph QA not found: {path}")
            return
        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    questions = d.get("questions", [])
                    answers = d.get("answers", [])
                    for q in questions:
                        for a in answers:
                            self.qa_pairs.append((q, a, "huatuo_kg"))
                            count += 1
                            if count >= 100000:  # 限制数量避免内存过大
                                break
                except json.JSONDecodeError:
                    pass
        print(f"  [OK] Huatuo KG QA: {count} 条QA对")

    def _load_huatuo_sft(self):
        """加载华佗GPT微调数据"""
        path = f"{self.base_dir}/HuatuoGPT-sft/HuatuoGPT_sft_data_v1.jsonl"
        if not os.path.exists(path):
            print(f"  [WARN] HuatuoGPT-sft not found: {path}")
            return
        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    data_list = d.get("data", [])
                    # data[0] = "问：xxx", data[1] = "答：xxx"
                    if len(data_list) >= 2:
                        q = str(data_list[0]).replace("问：", "").strip()
                        a = str(data_list[1]).replace("答：", "").strip()
                        if q and a and len(q) > 4:
                            self.qa_pairs.append((q, a, "huatuo_sft"))
                            count += 1
                            if count >= 50000:
                                break
                except json.JSONDecodeError:
                    pass
        print(f"  [OK] HuatuoGPT SFT: {count} 条QA对")

    def _load_shennong_tcm(self):
        """加载神农中医数据"""
        path = f"{self.base_dir}/ShenNong_TCM_Dataset/ChatMed_TCM-v0.2.json"
        if not os.path.exists(path):
            print(f"  [WARN] ShenNong TCM not found: {path}")
            return
        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    q = d.get("query", "")
                    a = d.get("response", "")
                    if q and a:
                        self.qa_pairs.append((q, a, "tcm"))
                        count += 1
                except json.JSONDecodeError:
                    pass
        print(f"  [OK] ShenNong TCM: {count} 条中医QA对")

    def _load_chatmed_consult(self):
        """加载ChatMed问诊数据"""
        path = f"{self.base_dir}/modelscope_ChatMed_Consult/ChatMed_Consult-v0.3.json"
        if not os.path.exists(path):
            print(f"  [WARN] ChatMed Consult not found: {path}")
            return
        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    q = d.get("query", "")
                    a = d.get("response", "")
                    if q and a:
                        self.qa_pairs.append((q, a, "chatmed"))
                        count += 1
                        if count >= 50000:
                            break
                except json.JSONDecodeError:
                    pass
        print(f"  [OK] ChatMed: {count} 条问诊QA对")

    def _load_chinese_medical_dialogue(self):
        """加载中文医疗对话数据（只取部分）"""
        path = f"{self.base_dir}/modelscope_Chinese-medical-dialogue/data/train_0001_of_0001.json"
        if not os.path.exists(path):
            print(f"  [WARN] Chinese medical dialogue not found: {path}")
            return
        count = 0
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for item in data[:100000]:  # 只取前10万条
                inst = item.get("instruction", "")
                inp = item.get("input", "")
                out = item.get("output", "")
                q = inst + (" " + inp if inp else "")
                if q and out:
                    self.qa_pairs.append((q, out, "med_dialogue"))
                    count += 1
            print(f"  [OK] Medical Dialogue: {count} 条对话对")
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"  [WARN] Medical Dialogue: {e}")

    def _load_synthetic_diseases(self):
        """加载模拟疾病数据"""
        path = f"{self.base_dir}/synthetic_diseases.json"
        if not os.path.exists(path):
            return
        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    name = d.get("name", "")
                    if not name or name in self.diseases:
                        continue
                    self.diseases[name] = {
                        "name": name,
                        "desc": d.get("desc", ""),
                        "category": d.get("category", []),
                        "symptom": d.get("symptom", []),
                        "cause": d.get("cause", ""),
                        "prevent": d.get("prevent", ""),
                        "cure_way": d.get("cure_way", []),
                        "cure_department": d.get("cure_department", []),
                        "cure_lasttime": d.get("cure_lasttime", ""),
                        "cured_prob": d.get("cured_prob", ""),
                        "check": d.get("check", []),
                        "recommand_drug": d.get("recommand_drug", []),
                        "drug_detail": d.get("drug_detail", []),
                        "cost_money": d.get("cost_money", ""),
                        "acompany": d.get("acompany", []),
                        "get_prob": d.get("get_prob", ""),
                        "get_way": d.get("get_way", ""),
                        "yibao_status": d.get("yibao_status", ""),
                    }
                    for s in d.get("symptom", []):
                        self.symptom_map[s].append(name)
                    for drug_str in d.get("drug_detail", []) + d.get("recommand_drug", []):
                        if isinstance(drug_str, str):
                            drug_name = drug_str.split("(")[0].strip()
                            if drug_name and len(drug_name) < 30:
                                self.drug_map[drug_name].append(name)
                    for dept in d.get("cure_department", []):
                        self.dept_map[dept].append(name)
                    self.term_dict.add(name)
                    for cat in d.get("category", []):
                        self.term_dict.add(cat)
                    count += 1
                except json.JSONDecodeError:
                    pass
        if count > 0:
            self.disease_index.extend([
                (name, info["desc"][:100], info["category"])
                for name, info in self.diseases.items()
                if name not in [x[0] for x in self.disease_index]
            ])
            print(f"  [OK] Synthetic Diseases: {count} 种疾病")

    def _load_synthetic_qa(self):
        """加载模拟QA数据"""
        path = f"{self.base_dir}/synthetic_qa.json"
        if not os.path.exists(path):
            return
        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    q = d.get("query", "")
                    a = d.get("response", "")
                    cat = d.get("category", "synthetic")
                    if q and a:
                        self.qa_pairs.append((q, a, f"synthetic_{cat}"))
                        count += 1
                except json.JSONDecodeError:
                    pass
        if count > 0:
            print(f"  [OK] Synthetic QA: {count} 条QA对")

    def _load_peizhen_exam_kb(self):
        """加载陪诊师考核知识库"""
        path = f"{self.base_dir}/peizhen_exam_kb.json"
        if not os.path.exists(path):
            print(f"  [WARN] 陪诊师考核知识库未找到: {path}")
            return
        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    q = d.get("query", "")
                    a = d.get("response", "")
                    cat = d.get("category", "peizhen_exam")
                    if q and a:
                        self.qa_pairs.append((q, a, f"peizhen_{cat}"))
                        count += 1
                except json.JSONDecodeError:
                    pass
        print(f"  [OK] 陪诊师考核题库: {count} 条QA对")

    def _build_term_index(self):
        """从QA对中提取额外的医学术语"""
        medical_pattern = re.compile(
            r'(?:[^\w\s])?'  # optional punctuation
            r'(?:急性|慢性|原发性|继发性|先天性|获得性|良性|恶性)?'
            r'(?:[一-龥]{2,6}'
            r'(?:病|症|炎|癌|瘤|肿|痛|热|咳|喘|泻|吐|晕|瘫|聋|盲|'
            r'出血|坏死|硬化|变性|缺损|障碍|衰竭|过敏|中毒|感染|'
            r'综合征|综合征|畸形|脱位|骨折|损伤|溃疡|结石)'
            r')'
        )
        for q, a, _ in self.qa_pairs[:50000]:
            for term in medical_pattern.findall(q + a):
                self.term_dict.add(term)

    def _tokenize(self, text):
        """中文分词 — 优先 jieba.lcut（比 cut 快），降级 bigram+unigram"""
        if _JIEBA_AVAILABLE:
            tokens = []
            for word in jieba.lcut(text):
                word = word.strip()
                if word and len(word) >= 1 and not re.match(r'^[\s\d\W_]+$', word):
                    tokens.append(word)
            # 补充 unigram（保留单字，中文单字有重要语义，但不重复添加已被分词覆盖的）
            seen = set(tokens)
            for ch in text:
                if '一' <= ch <= '鿿' and ch not in seen:
                    tokens.append(ch)
            return tokens

        # Fallback: bigram + unigram
        cleaned = re.sub(r'[^一-鿿\w]', ' ', text.lower())
        tokens = []
        chars = cleaned.replace(' ', '')
        for ch in chars:
            if ch.strip():
                tokens.append(ch)
        for i in range(len(chars) - 1):
            bigram = chars[i:i+2]
            if not bigram[0].isspace() and not bigram[1].isspace():
                tokens.append(bigram)
        for w in cleaned.split():
            if len(w) >= 2 and w.isalpha():
                tokens.append(w)
        return tokens

    def _build_qa_index(self):
        """构建 QA 倒排索引 + IDF 值，支持 BM25 检索

        索引上限 250K 条（质量优先），跳过过短/低质量 QA
        """
        MAX_INDEX = 250000
        print(f"  构建 QA 倒排索引（上限 {MAX_INDEX} 条）...")
        self.qa_docs = []
        self.qa_inverted = defaultdict(list)
        self.qa_doc_lengths = []
        self.qa_idf = {}
        self.qa_avg_dl = 0
        self.qa_source_index = defaultdict(list)

        df = Counter()
        indexed = 0
        skipped_empty = 0
        skipped_short = 0

        for doc_id, (q, a, src) in enumerate(self.qa_pairs):
            if indexed >= MAX_INDEX:
                break
            # 跳过空内容或过短 QA
            if not q or not a:
                skipped_empty += 1
                continue
            if len(q) < 5 or len(a) < 10:
                skipped_short += 1
                continue

            text = q + ' ' + a
            tokens = self._tokenize(text)
            if not tokens:
                continue

            self.qa_docs.append((q, a, src))
            self.qa_doc_lengths.append(len(tokens))
            self.qa_source_index[src].append(indexed)
            indexed += 1

            tf = Counter(tokens)
            for token, count in tf.items():
                self.qa_inverted[token].append((indexed - 1, count))
                df[token] += 1

        N = len(self.qa_docs)
        for token, freq in df.items():
            self.qa_idf[token] = math.log((N - freq + 0.5) / (freq + 0.5) + 1.0)

        self.qa_avg_dl = sum(self.qa_doc_lengths) / max(N, 1)
        print(f"  [OK] QA 索引: {len(self.qa_inverted)} 个 token, "
              f"平均文档长度 {self.qa_avg_dl:.1f}")
        if skipped_empty or skipped_short:
            print(f"       跳过空/过短: {skipped_empty + skipped_short} 条")

    def _print_stats(self):
        print("-" * 60)
        print(f"  总计: {len(self.diseases)} 疾病 | "
              f"{len(self.qa_pairs)} QA对 | "
              f"{len(self.term_dict)} 术语")
        print(f"  症状索引: {len(self.symptom_map)} | "
              f"  药品索引: {len(self.drug_map)} | "
              f"  科室索引: {len(self.dept_map)}")
        print("=" * 60)


# ═══════════════════════════════════════════════════════════
# 2. 检索层
# ═══════════════════════════════════════════════════════════

class MedicalTermSearch:
    """医疗专业术语搜索引擎"""

    def __init__(self, kb):
        self.kb = kb

    def fuzzy_match(self, query, candidates, top_k=10, threshold=0.3):
        """模糊匹配"""
        results = []
        for item in candidates:
            if isinstance(item, tuple):
                text = item[0]  # (name, desc, category)
            else:
                text = str(item)
            sim = SequenceMatcher(None, query.lower(), text.lower()).ratio()
            # 也检查子串包含
            if query.lower() in text.lower():
                sim = max(sim, 0.7)
            if sim >= threshold:
                results.append((text, sim, item))
        results.sort(key=lambda x: -x[1])
        return results[:top_k]

    def search_disease(self, query):
        """搜索疾病 - 返回结构化医学术语信息"""
        # 1. 精确匹配
        if query in self.kb.diseases:
            return [(query, 1.0, self.kb.diseases[query])]

        # 2. 模糊匹配疾病名
        fuzzy = self.fuzzy_match(query, self.kb.disease_index, top_k=5, threshold=0.3)
        if fuzzy:
            return [(name, sim, self.kb.diseases.get(name, info))
                    for name, sim, info in fuzzy]

        return []

    def search_by_symptom(self, query):
        """通过症状搜索可能疾病 — 从自然语言中提取症状关键词"""
        results = []
        q = query.lower()
        for sym, diseases in self.kb.symptom_map.items():
            sym_lower = sym.lower()
            # 检查症状词是否出现在查询中
            if sym_lower in q or SequenceMatcher(None, sym_lower, q).ratio() > 0.6:
                score = len(sym_lower) / max(len(q), 1) + 0.5  # 长症状词更精准
                for d in diseases[:5]:
                    if d in self.kb.diseases:
                        results.append((d, sym, score))
        results.sort(key=lambda x: -x[2])
        return [(d, sym) for d, sym, _ in results[:10]]

    def search_by_drug(self, query):
        """通过药品搜索相关疾病 — 双向模糊匹配（药品名↔查询）"""
        results = []
        q = query.lower()
        for dname, diseases in self.kb.drug_map.items():
            dname_lower = dname.lower()
            # 双向匹配：药品名包含查询 或 查询包含药品名
            if q in dname_lower or dname_lower in q:
                for d in diseases[:5]:
                    if d in self.kb.diseases:
                        results.append((d, dname))
        return results[:10]

    def search_department(self, query):
        """陪诊场景：从查询中提取症状，推荐就诊科室"""
        # 先找症状关联的疾病，再提取科室
        diseases_from_symptom = self.search_by_symptom(query)
        dept_results = {}
        for d_name, matched_sym in diseases_from_symptom:
            info = self.kb.diseases.get(d_name, {})
            depts = info.get("cure_department", [])
            for dept in depts:
                if dept not in dept_results:
                    dept_results[dept] = {"diseases": [], "symptoms": set()}
                dept_results[dept]["diseases"].append(d_name)
                dept_results[dept]["symptoms"].add(matched_sym)
        # 按关联疾病数排序
        sorted_depts = sorted(dept_results.items(), key=lambda x: -len(x[1]["diseases"]))
        return [{"department": d, "diseases": v["diseases"][:3],
                 "matched_symptoms": list(v["symptoms"])}
                for d, v in sorted_depts[:5]]

    def search_qa(self, query, top_k=5, source_filter=None):
        """BM25 加权检索 QA 对 — 全量扫描，智能排序

        Args:
            query: 搜索查询
            top_k: 返回结果数
            source_filter: 可选，只搜索特定来源（如 'peizhen' 只搜陪诊相关）
        """
        if not hasattr(self.kb, 'qa_inverted') or not self.kb.qa_inverted:
            # fallback to old method if index not built
            return self._search_qa_fallback(query, top_k)

        N = len(self.kb.qa_docs)
        if N == 0:
            return []

        query_tokens = self.kb._tokenize(query)
        if not query_tokens:
            return []

        k1 = 1.2   # BM25 term saturation
        b = 0.75   # length normalization

        # accumulate scores per doc
        scores = defaultdict(float)
        qt_counter = Counter(query_tokens)

        for token, qtf in qt_counter.items():
            if token not in self.kb.qa_inverted:
                continue
            idf = self.kb.qa_idf.get(token, 0)
            for doc_id, tf in self.kb.qa_inverted[token]:
                # source filter
                if source_filter and self.kb.qa_docs[doc_id][2] not in source_filter:
                    continue
                dl = self.kb.qa_doc_lengths[doc_id]
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * dl / self.kb.qa_avg_dl)
                scores[doc_id] += idf * numerator / denominator

        # also boost by raw substring match (helps with very specific queries)
        q_lower = query.lower()
        for doc_id in list(scores.keys()):
            q_text = self.kb.qa_docs[doc_id][0].lower()
            a_text = self.kb.qa_docs[doc_id][1].lower()
            if q_lower in q_text:
                scores[doc_id] *= 1.5
            elif q_lower in a_text:
                scores[doc_id] *= 1.2

        # sort and return top_k
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
        return [
            (self.kb.qa_docs[doc_id][0],
             self.kb.qa_docs[doc_id][1],
             self.kb.qa_docs[doc_id][2],
             round(score, 3))
            for doc_id, score in ranked
        ]

    def _search_qa_fallback(self, query, top_k=5):
        """后备方法：关键词匹配"""
        results = []
        q = query.lower()
        keywords = [w for w in q.replace("？", "").replace("，", " ").replace("的", " ").split()
                    if len(w) >= 2]
        for i, (question, answer, source) in enumerate(self.kb.qa_pairs):
            ql = question.lower()
            al = answer.lower()
            score = 0
            for kw in keywords:
                if kw in ql:
                    score += 2
                if kw in al:
                    score += 1
            if score > 0:
                results.append((question, answer, source, score))
            if len(results) >= top_k * 5:
                break
        results.sort(key=lambda x: -x[3])
        return results[:top_k]

    def search_all_terms(self, query):
        """在所有术语中搜索"""
        results = []
        q = query.lower()
        for term in self.kb.term_dict:
            if q in term.lower():
                results.append(term)
            elif SequenceMatcher(None, q, term.lower()).ratio() > 0.6:
                results.append(term)
        # 按匹配度排序
        results.sort(key=lambda t: SequenceMatcher(None, q, t.lower()).ratio(), reverse=True)
        return results[:20]


# ═══════════════════════════════════════════════════════════
# 3. 格式化输出层
# ═══════════════════════════════════════════════════════════

def format_disease_response(disease_info):
    """格式化疾病信息为专业医学术语回复"""
    d = disease_info
    lines = []
    lines.append("═" * 58)
    lines.append(f"  【疾病名称】{d.get('name', '未知')}")
    lines.append("═" * 58)

    if d.get("category"):
        lines.append(f"  【分类】{' › '.join(d['category'])}")

    if d.get("desc"):
        desc = d["desc"]
        lines.append(f"  【概述】{desc[:200]}{'...' if len(desc) > 200 else ''}")

    if d.get("symptom"):
        symptoms = d["symptom"]
        if isinstance(symptoms, list):
            lines.append(f"  【症状】{'、'.join(symptoms[:10])}")
        else:
            lines.append(f"  【症状】{symptoms}")

    if d.get("cause"):
        lines.append(f"  【病因】{d['cause'][:200]}")

    if d.get("cure_department"):
        lines.append(f"  【就诊科室】{'、'.join(d['cure_department'])}")

    if d.get("check"):
        checks = d["check"]
        if isinstance(checks, list):
            lines.append(f"  【检查项目】{'、'.join(checks[:10])}")
        else:
            lines.append(f"  【检查项目】{checks}")

    if d.get("cure_way"):
        cures = d["cure_way"]
        if isinstance(cures, list):
            lines.append(f"  【治疗方式】{'、'.join(cures[:10])}")
        else:
            lines.append(f"  【治疗方式】{cures}")

    if d.get("recommand_drug"):
        drugs = d["recommand_drug"]
        if isinstance(drugs, list):
            lines.append(f"  【推荐药品】{'、'.join(drugs[:10])}")
        else:
            lines.append(f"  【推荐药品】{drugs}")

    if d.get("drug_detail"):
        drug_strs = [str(dd) for dd in d["drug_detail"][:8]]
        lines.append(f"  【用药详情】{'；'.join(drug_strs)}")

    if d.get("cured_prob"):
        lines.append(f"  【治愈概率】{d['cured_prob']}")

    if d.get("cure_lasttime"):
        lines.append(f"  【治疗周期】{d['cure_lasttime']}")

    if d.get("cost_money"):
        lines.append(f"  【预估费用】{d['cost_money']}")

    if d.get("prevent"):
        lines.append(f"  【预防措施】{d['prevent'][:200]}")

    if d.get("acompany"):
        acc = d["acompany"]
        if isinstance(acc, list):
            lines.append(f"  【并发症】{'、'.join(acc[:10])}")
        else:
            lines.append(f"  【并发症】{acc}")

    if d.get("get_prob"):
        lines.append(f"  【发病率】{d['get_prob']}")

    if d.get("get_way"):
        lines.append(f"  【传播途径】{d['get_way']}")

    if d.get("yibao_status"):
        lines.append(f"  【医保状态】{d['yibao_status']}")

    lines.append("═" * 58)
    return "\n".join(lines)


def format_qa_response(qa_results):
    """格式化QA回复"""
    if not qa_results:
        return "未找到相关问答。"
    lines = ["", "─" * 58, "  【相关医疗问答】", "─" * 58]
    for i, (q, a, source, score) in enumerate(qa_results, 1):
        lines.append(f"\n  [{i}] [{source}] Q: {q[:100]}{'...' if len(q)>100 else ''}")
        lines.append(f"      A: {a[:300]}{'...' if len(a)>300 else ''}")
    lines.append("─" * 58)
    return "\n".join(lines)


def format_symptom_response(symptoms, label="症状"):
    """格式化症状→疾病回复"""
    if not symptoms:
        return f"未通过{label}匹配到相关疾病。"
    lines = ["", "─" * 58, f"  【{label}关联疾病】", "─" * 58]
    for d_name, sym in symptoms:
        info = kb.diseases.get(d_name, {})
        desc = info.get("desc", "")[:80]
        lines.append(f"  ● {d_name} (匹配{label}: {sym})")
        if desc:
            lines.append(f"    {desc}")
    lines.append("─" * 58)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 4. 主入口
# ═══════════════════════════════════════════════════════════

def interactive_mode(search):
    """交互式查询模式"""
    print("\n" + "=" * 60)
    print("  陪优佳检索系统")
    print("=" * 60)
    print("  命令:")
    print("    disease <病名>    查询疾病专业术语")
    print("    symptom <症状>    通过症状查疾病")
    print("    drug <药品>       通过药品查疾病")
    print("    qa <问题>         搜索医疗问答")
    print("    term <术语>       搜索所有术语")
    print("    stats             显示知识库统计")
    print("    quit              退出")
    print("=" * 60)

    while True:
        try:
            cmd = input("\n🔍 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出。")
            break

        if not cmd:
            continue
        if cmd.lower() == "quit":
            break
        if cmd.lower() == "stats":
            kb._print_stats()
            continue

        parts = cmd.split(maxsplit=1)
        if len(parts) < 2:
            print("  格式: <命令> <查询内容>")
            continue

        action, query = parts

        if action == "disease":
            results = search.search_disease(query)
            if results:
                for name, sim, info in results:
                    print(format_disease_response(info))
                    if sim < 1.0:
                        print(f"  (模糊匹配, 相似度: {sim:.2f})")
            else:
                print(f"  未找到匹配疾病: {query}")
                # 尝试术语搜索
                terms = search.search_all_terms(query)
                if terms:
                    print(f"\n  相关术语: {'、'.join(terms[:15])}")

        elif action == "symptom":
            results = search.search_by_symptom(query)
            print(format_symptom_response(results))

        elif action == "drug":
            results = search.search_by_drug(query)
            if results:
                print(format_symptom_response(results, "药品"))
            else:
                print(f"  未找到药品: {query}")

        elif action == "qa":
            results = search.search_qa(query, top_k=5)
            print(format_qa_response(results))

        elif action == "term":
            results = search.search_all_terms(query)
            if results:
                print(f"\n  匹配术语 ({len(results)}):")
                for t in results:
                    print(f"    ● {t}")
            else:
                print(f"  未找到匹配术语: {query}")

        else:
            print(f"  未知命令: {action}")


def single_query(search, action, query):
    """单次查询模式"""
    if action == "disease":
        results = search.search_disease(query)
        for name, sim, info in results:
            print(format_disease_response(info))
        if not results:
            terms = search.search_all_terms(query)
            if terms:
                print(f"\n  相关术语: {'、'.join(terms[:15])}")

    elif action == "symptom":
        results = search.search_by_symptom(query)
        print(format_symptom_response(results))

    elif action == "drug":
        results = search.search_by_drug(query)
        if results:
            print(format_symptom_response(results))

    elif action == "qa":
        results = search.search_qa(query)
        print(format_qa_response(results))

    elif action == "term":
        results = search.search_all_terms(query)
        if results:
            print(f"\n  匹配术语 ({len(results)}):")
            for t in results:
                print(f"    ● {t}")

    else:
        print(f"未知操作: {action}")
        print("支持: disease, symptom, drug, qa, term")


# ═══════════════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 修复 Windows GBK 编码问题
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    # 初始化知识库
    kb = MedicalKnowledgeBase()
    kb.load_all()
    search = MedicalTermSearch(kb)

    if len(sys.argv) >= 3:
        # 命令行模式: python med_term_kb.py <action> <query>
        action = sys.argv[1]
        query = sys.argv[2]
        single_query(search, action, query)
    elif len(sys.argv) == 2 and sys.argv[1] in ("interactive", "-i"):
        # 交互模式
        interactive_mode(search)
    else:
        # 默认交互模式
        interactive_mode(search)
