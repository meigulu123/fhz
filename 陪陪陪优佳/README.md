# 陪优佳

智能陪诊与医疗健康问答 Web 应用。

## 功能

- **医疗健康问答**：疾病、症状、药品、科室的多路检索与智能回答
- **陪诊模拟**：模拟患者对话，训练陪诊沟通流程
- **语音播报**（TTS，需额外下载模型，见下文）

## 技术栈

- 后端：Python + Flask
- 前端：原生 HTML / CSS / JS 单页应用（`templates/index.html`）
- 检索：jieba 分词 + BM25 + 模糊匹配

## 运行

```bash
pip install flask flask-cors jieba
python server.py
# 浏览器访问 http://localhost:5000
```

## 数据说明（本仓库未包含）

知识库依赖以下第三方医疗数据集（共约 4.5GB，请自行下载后放到项目根目录）：

- DiseaseKG-CN —— 疾病知识图谱
- HuatuoGPT-sft —— 华佗医疗问答
- huatuo_knowledge_graph_qa —— 知识图谱 QA
- ShenNong_TCM_Dataset —— 中医对话
- modelscope_ChatMed_Consult / Chinese-medical-dialogue / SoulChatCorpus —— 问诊与心理对话
- CareGPT-YL / cMedQA2 / diaKG-code —— 药品、导诊等

## 语音模型说明（本仓库未包含）

TTS 语音功能依赖以下文件，可用 `python download_tts_models.py` 下载：

- `static/js/` —— onnxruntime-web 运行时
- `static/tts/` 或 `static/tts-model/` —— VITS 中文语音模型（单个约 116MB）

## 免责声明

本应用内容仅供参考，不能替代专业医疗诊断。如有不适请及时就医。
