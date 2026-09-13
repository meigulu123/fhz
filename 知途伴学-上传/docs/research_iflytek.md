# 科大讯飞生态对接调研报告

> 项目：知途伴学（中国国际大学生创新大赛 2026 产业命题赛道，命题企业：科大讯飞）
> 调研方式：WebSearch/WebFetch（本环境下 www.xfyun.cn、docs.iflyaicloud.com 等官方站点无法直接抓取原文，官方文档内容经由搜索结果中转核实，标注为准）
> 检索日期：2026-09-12
> 原则：只记录查证到的信息，每条标注来源；未查到即注明"未查到公开信息"。

---

## 主题一：星火大模型 API 接入方式

### 1.1 官方入口与文档地址

| 项目 | 地址 |
|---|---|
| 讯飞开放平台（注册/控制台） | https://www.xfyun.cn/ ；控制台 https://console.xfyun.cn/ |
| 星火大模型官网（领取免费额度入口） | https://xinghuo.xfyun.cn/ |
| WebSocket 接口文档（星火认知大模型 websocket 接口文档） | https://www.xfyun.cn/doc/spark/Web.html |
| HTTP 协议文档（Spark-X2 http 协议文档，含通用 HTTP 调用说明） | https://www.xfyun.cn/doc/spark/X1http.html |
| Spark-X2 websocket 协议文档 | https://www.xfyun.cn/doc/spark/X1ws.html |
| Spark-X2-Flash http 协议文档 | https://www.xfyun.cn/doc/spark/X2-Flash.html |
| 星辰 MaaS 产品文档（Spark Lite 等模型文档） | https://docs.iflyaicloud.com/project-3/ |

### 1.2 OpenAI 兼容 HTTP 接口（推荐本项目使用的接入方式）

- **Base URL**：`https://spark-api-open.xf-yun.com/v1/chat/completions`（即 OpenAI 兼容端点 `https://spark-api-open.xf-yun.com/v1`）
  - 直接使用 OpenAI SDK 时 baseURL 填 `https://spark-api-open.xf-yun.com/v1`
  - 使用 Spring AI 的 OpenAI starter 等会自动补 `/v1` 的框架时，base-url 只填 `https://spark-api-open.xf-yun.com`
- **深度推理模型（X1/X2）专用端点**：`https://spark-api-open.xf-yun.com/v2/chat/completions`（X1http 文档所述；使用 OpenAI SDK 时 base_url 为 `https://spark-api-open.xf-yun.com/v2/`）
- **鉴权**：请求头 `Authorization: Bearer <凭证>`。
  - 多篇实操教程给出两种写法并存：(a) `Bearer APIKey:APISecret`（通用版本，多个开源项目如 RAGFlow 集成采用）；(b) `Bearer APIPassword`（X1http 文档口径，仅一个密码参数）。
  - **接入时务必以控制台"我的应用"页面实际下发的 APIKey/APISecret/APIPassword 字段为准**，两种写法均有多来源佐证，建议先各试一次。
- **model 参数取值**（HTTP 接口，多来源交叉验证）：

| model 值 | 对应版本 | 说明 |
|---|---|---|
| `lite` | Spark Lite | 免费轻量版，2 QPS；注意教程明确提醒**不要写成 `spark-lite`**（部分第三方中转工具也用 `spark-lite`，以官方文档/控制台为准） |
| `generalv3` | Spark Pro | 8K 上下文，支持 function calling、system prompt |
| `generalv3.5` | Spark Max | 8K 上下文，千亿参数旗舰（注意：Max 套餐 2026-03-10 已下线，后端升级为 Ultra） |
| `pro-128k` | Spark Pro-128K | 128K 长上下文 |
| `max-32k` | Spark Max-32K | 32K 上下文 |
| `4.0Ultra` | Spark 4.0 Ultra | 综合旗舰，32K，支持流式、工具调用，已升级 X1.5 快思考模式 |
| `x1`（X1 系列另有 x1-0420、x1-0720 版本） | 星火深度推理 X1 | 深度推理，国产算力训练，对标 OpenAI o1 / DeepSeek R1 |
| Spark X2 系列 | 星火深度推理 X2 | 2026-02-11 发布，针对教育、医疗、汽车、智能体四大场景强化 |
| `general` / `generalv2` | 旧版本 | 部分来源称 HTTP 接口仍接受旧模型名 |

- **接口行为要点**：
  - 请求/响应兼容 OpenAI 格式（messages、temperature、max_tokens、stream 等），流式返回 SSE `chat.completion.chunk`，`choices[].delta` 含 `reasoning_content`（思维链，仅推理模型）与 `content`
  - 有来源反馈该接口返回格式并非 100% 标准 OpenAI 格式，使用 oneapi 等中转工具时可能受影响，本项目直接调 SDK 影响较小
  - 旧域名已停用，务必使用 `spark-api-open.xf-yun.com`（2025 年起的新域名）
  - 1 token ≈ 1.5 个中文字 / 0.8 个英文单词，输入+输出均计费

### 1.3 原生 WebSocket 接口（备选）

- Spark Lite 请求地址：`wss://spark-api.xf-yun.com/v1.1/chat`，domain 参数 `lite`；Max 为 `wss://spark-api.xf-yun.com/v3.5/chat`；Pro 为 `wss://spark-api.xf-yun.com/v3.1/chat`（各版本地址以官方 Web 文档为准）
- 鉴权：APPID + APIKey + APISecret 三件套，HMAC-SHA256 签名（比 HTTP 方式复杂）
- 官方文档明确列出的通用版本共六个：Lite、Pro、Pro-128K、Max、Max-32K、4.0 Ultra，另有科技文献大模型（kjwx）；对应 domain 参数如 `lite`、`4.0Ultra` 等

### 1.4 申请流程（多篇教程一致）

1. 在 https://xinghuo.xfyun.cn/ 或 https://www.xfyun.cn/ 用手机号注册
2. **完成个人实名认证**（姓名、身份证号、单位/学校、职位；未实名无法创建应用、无法领取免费额度——教程称这一步卡住约 90% 新手；也有 2026 年教程称领取部分免费额度无需实名，以实际页面为准）
3. 控制台 → 我的应用 → 创建应用；**服务类型务必选"星火认知大模型"**（选成语音合成/识别会导致 APIKey 报 403）
4. 审核约 3–5 分钟自动通过；应用详情页获取 **APPID / APIKey / APISecret**（密钥关闭页面后不可再查看，只能重置）
5. 领取免费额度包并**绑定到该应用**（只有购买了免费包的应用才能调用）
6. 调用限制：免费版约 2 QPS、部分来源称约 1000 次/天的限额

**主题一来源 URL**：
- https://www.xfyun.cn/doc/spark/Web.html
- https://www.xfyun.cn/doc/spark/X1http.html
- https://www.xfyun.cn/doc/spark/X1ws.html
- https://www.xfyun.cn/doc/spark/X2-Flash.html
- https://docs.iflyaicloud.com/project-3/
- https://liuyueyi.github.io/tutorial/spring/springai/%E5%9F%BA%E7%A1%80%E7%AF%87/15.%E6%8E%A5%E5%85%A5OpenAI%E6%8E%A5%E5%8F%A3%E9%A3%8E%E6%A0%BC%E7%9A%84%E5%A4%A7%E6%A8%A1%E5%9E%8B.html
- https://www.hhui.top/spring-blog/2025/08/26/250826-SpringAI%E4%B9%8B%E6%8E%A5%E5%85%A5OpenAI%E6%8E%A5%E5%8F%A3%E9%A3%8E%E6%A0%BC%E7%9A%84%E5%A4%A7%E6%A8%A1%E5%9E%8B/
- https://jishuzhan.net/article/1928625158159380481
- https://github.com/alibaba/open-code-review/pull/485
- https://github.com/infiniflow/ragflow/blob/09d45046e5f46fb2300f8860a3819568d71916d3/rag/llm/chat_model.py
- https://blog.csdn.net/hhhhhhhhhhwwwwwwwwww/article/details/139843713
- https://blog.csdn.net/shy_snow/article/details/149705073
- https://blog.csdn.net/weixin_68126124/article/details/148562703
- https://cloud.tencent.cn/developer/article/2703427
- https://www.cnblogs.com/ubuntulolo/p/19748651
- https://m.php.cn/faq/2709590.html
- https://docs.rs/anyllm_providers/latest/src/anyllm_providers/providers/iflytek.rs.html
- https://linux.do/t/topic/95606/49
- http://aikkm.com/models/series/%E6%98%9F%E7%81%AB(Spark)

---

## 主题二：免费额度政策（2025–2026）

### 2.1 面向个人开发者的免费额度（多来源交叉，标注冲突处）

| 模型 | 免费政策 | 说明与限制 |
|---|---|---|
| Spark Lite | **永久免费、不限量** | 官方 2024-06 起的长期承诺（"普惠政策"）；QPS=2；上下文较短（约 2K）；不支持 system 角色、不返回信源链接、不能调插件 |
| Spark Pro | 个人用户每月最高 **400 万 tokens**（基础 200 万/月，用完可点"申请加油包"再领 200 万） | 按月清零、月初自动补满；额度用完自动暂停，不产生扣费；支持全部内置插件与多轮对话；部分来源称新用户注册即送 100 万+200 万（V1.5/V2.0 版本各计） |
| Spark Max | 曾免费赠送 **1 亿 tokens**（2024 普惠政策，面向开发者/创业团队） | **注意：Max 版本套餐已于 2026-03-10 下线，授权用量与 Ultra 合并，官方推荐改用 Ultra** |
| Spark 4.0 Ultra | 来源冲突：一说可免费领 200 万 tokens（有效期 1 年，需实名认证）；一说免费用户不可用需购套餐；普惠政策口径为"首单买一送一" | 以开放平台实时页面为准 |
| 星火多语种大模型 | 个人开发者免费试用包：**200 万 tokens，QPS 2，有效期 1 年** | — |
| 企业认证 | 有来源称个人认证领 200 万、转企业认证再领 500 万（共 700 万，免费试用一年） | 早期政策口径，时效性存疑 |

- 政策脉络：2024-06-26 科大讯飞发布"讯飞星火 API 普惠政策"（Lite 永久免费、Pro 免费试用 1 个月、Max 送 1 亿 tokens、4.0 Ultra 首单买一送一、技术专家 1V1 支持）；2024-09-25 API 升级延续"加量不加价"。**2026 年未查到普惠政策再次调整的公开信息，Max 下线是 2026 年已知的最大变化。**
- 付费参考：Spark Pro 月付约 99 元含 1000 万 tokens；X2 约 2–3 元/百万 tokens（不同时期报价，仅供参考）。

### 2.2 高校学生专属政策

- **未查到讯飞开放平台面向高校学生的独立"校园认证/学生专属免费额度"政策的公开信息**（检索"高校学生 校园认证 教育优惠"等关键词无结果）。
- 与学生最相关的政策是：
  - **"星火杯"大模型应用创新赛**（共青团安徽省委、安徽省教育厅、省科技厅、省学联、科大讯飞共同主办）：2024 年向参赛大学生**免费开放星火七大 API 能力**；2026 年第四届（智能体创新赛道）为参赛团队提供**星辰 MaaS 平台 88 元模型调用额度**及语音转写/合成等 AI 原子能力，总奖池 25 万元。赛事官网 https://challenge.xfyun.cn/xinghuo
  - 个人开发者免费包本身无需企业资质、无需付费，学生以个人身份注册即可领取（教程称约 3 分钟完成，多数来源称无需实名/绑卡，亦有来源称需实名，以页面为准）。

### 2.3 领取路径

星火官网 https://xinghuo.xfyun.cn/ → 点"API 免费使用" → 服务管理页"立即领取"（自动创建应用并开通 Spark Pro 权限）→ 控制台获取三组密钥 → 在应用管理页对所选模型（如 Spark Lite / Pro）点"开通服务/免费领取（0 元购买）"→ 用量统计中查看剩余额度。

**主题二来源 URL**：
- https://www.php.cn/faq/2709559.html ；https://m.php.cn/faq/2709559.html
- https://www.php.cn/faq/2791807.html
- https://m.chinaz.com/ainews/11972.shtml
- https://www.aitop100.cn/infomation/details/19256.html
- http://damoai.com.cn/kuaixun/6079.html
- https://www.sohu.com/a/788618575_120988576
- https://g.pconline.com.cn/x/1761/17613208.html
- https://www.pmkg.net/sites/4470.html
- https://yangmao.ai/zh/providers/spark/
- https://www.xfyun.cn/services/multilang
- https://news.zol.com.cn/878/8786705.html
- https://m.ikanchai.com/pcarticle/591127
- https://challenge.xfyun.cn/xinghuo?ch=iEHjkcg ；https://challenge.xfyun.cn/h5/home?ch=ky
- https://www.sohu.com/a/1056396007_122105141
- https://gitcode.csdn.net/69fdd8ba54b52172bc727ca3.html

---

## 主题三：智学网与智慧教育生态

### 3.1 智学网：K12 大数据精准教学系统

- **产品定位**：智学网由科大讯飞全资子公司安徽知学科技有限公司运营，2014 年 1 月上线，是面向**学校日常作业、考试及发展性教与学评价**的大数据个性化教学（教与学）系统，分教师端、学生端、家长端，官方表述为"面向**新高考、新课改**需求"。
- **核心能力**：基于 AI、知识图谱与大数据，采集随堂测验、阶段考、联考等全场景过程性数据；中英文作文自动评分与智能批改；生成 15 个模块、80 多项指标的学业分析报告；学生端有个性化学情分析、个性化学习资源推荐、智能错题本（"少做题、做好题、做对题"）。
- **覆盖规模**：截至 2025 年覆盖全国 32 个省级行政区 3 万余所学校、受益师生超 4500 万；覆盖华东师大二附、人大附、衡水中学等超半数百强校。
- **历史争议**：早期向家长收取会员费（"学霸套餐"1 年 365 元）引发"查成绩需付费"投诉；2018 年教育部禁止有害 APP 进校园后，讯飞取消成绩排名展示与向学生收费，推出免费学生端 APP。
- **是否覆盖大学段**：**未查到智学网覆盖高校的可靠证据**（仅一个低权威 wiki 声称有高校课程资源，与其他官方口径矛盾，不采信）。

### 3.2 讯飞学习机 AI 1对1（C 端硬件旗舰）

2025-06-24 合肥"AI 1对1 新进化 新伙伴"暑期发布会宣布三大核心功能升级 + 16 大功能上新（7 月中旬向老用户免费推送）：
- **AI 1对1 精准学**："测—学—练"闭环；新增**互动式问诊规划**——AI 像真人老师一样多轮对话后，结合能力层级、学习习惯、可投入时间、本地考试重点等生成个性化学习规划路径；AI 组卷扩展至小学+初中数学全题型
- **AI 1对1 答疑辅导**：启发式提问不直接给答案，支持结构化讲题；新增小学数学、初中语文、初中数学
- **AI 1对1 互动课**：沉浸式互动教学，覆盖幼小初高全学段；新课标体系课由教育部课标修订组专家指导审核
- 背景数据：讯飞智慧教育已服务全国 32 个省级行政区、5 万余所学校、1.3 亿师生；AI 学习机连续 5 年全国高端学习机销售额销量双第一，6000 元以上价位线上占比 49%（2026 上半年）

### 3.3 讯飞在高校/大学段的智慧教育产品与布局

- **组织与产品**：设有高教事业群/高教事业部/高教产品线；2025 年以来主打：
  - "**星火+DeepSeek 双引擎大模型智慧校园基座**"（AI 中台、知识与数据大脑、国产化硬件底座）
  - "**星火校园百事通**"：校园 AI 助手（语音交互、智能排课、个性化问答），已落地 20 余所高校、日均服务请求超 50 万次
  - 一体化智能教学平台（建备教、学测评、督管全链条）、AI 智慧考试/智能阅卷、课堂教学智能评价、新型智慧教学空间/未来学习中心
  - 2025 年年报研发项目中的"**讯飞AI课程**"（面向高校教务处及教师的混合式智慧教学平台与课程建设服务），研发投入仅约 **1576 万元**
- **大学段是否薄弱——查证结论：是，相对薄弱（有财报佐证）**：
  - 2025 年报研发投入中，K12 各项（学习机辅学约 2.42 亿、智能批阅机约 2860 万、大精产品约 2405 万、数智作业约 1991 万等）远高于高校唯一的"讯飞AI课程"（约 1576 万）
  - 涉高校业务主要是**考试评测服务的技术外溢**（四六级口语、考研、法考等），而非成规模的高等教育教学业务
  - 官方品牌简介（edu.iflytek.com）产品体系与里程碑事件均以中小学/基础教育为核心
  - 2026 上半年智慧教育收入 34.90 亿（占 30.03%），首次被开放平台业务反超；公司战略为"做强 C 端、做深 B 端、优选 G 端"
- **对本项目的含义**：大学段是讯飞智慧教育的短板与增量空间，一个面向高校场景、基于星火 API 的应用型产品（如本项目）恰好补位其大学段生态，具备与讯飞合作的叙事空间。

**主题三来源 URL**：
- https://baike.baidu.com/item/%E6%99%BA%E5%AD%A6%E7%BD%91 ；https://baike.baidu.com/item/%E6%99%BA%E5%AD%A6%E7%BD%91-%E5%AE%B6%E9%95%BF%E7%89%88/24249824
- https://mp.weixin.qq.com/s?__biz=MzA5NjYyMTA0OA==&mid=2649241908&idx=1&sn=d6726e93b943770f0315490dd82a995c&chksm=88b1c1a3bfc648b5100b1bd8690b64513a682b467b45d0c654377d61e507b80deededde6af82
- https://finance.sina.cn/2023-02-02/detail-imyehims9972075.d.html
- http://www.ah.xinhua.org/20250625/58345995a57349d2b1f68b9a469dfc3c/c.html
- https://i.ifeng.com/c/8kT8rd3jHK0
- https://www.ccidnet.com/p1/hlw/20250624/1016583.html
- https://news.sciencenet.cn/htmlnews/2025/6/546656.shtm
- https://www.stdaily.com/web/gdxw/2025-06/25/content_360337.html
- http://m.mydrivers.com/newsview/1056064.html
- https://www.pingwest.com/w/305789
- http://www.sxjybk.com/2025/0625/118075.html
- https://edu.iflytek.com/about-us/company
- https://www.szse.cn/disclosure/listed/bulletinDetail/index.html?33641b3f-c9da-41e1-900c-cdab9dd17b91=
- https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12252781
- https://www.usmart.hk/zh-cn/news-detail/7071808244162871655
- https://www.ofweek.com/ai/2026-05/ART-201717-8460-30686683.html
- http://www.21jingji.com/article/20260824/herald/ddc748ebd7ae225d89dd356b316f2e62.html
- https://www.jiemian.com/article/13229848.html
- https://www.hljut.edu.cn/a/xyxw/jxky/11408.html
- https://www.scpcfe.cn/ictr/info/1008/2381.htm
- http://www.tze.cn/index.php?r=space/school/portal/content/view&sid=1602f50408804d238cd48d7ce0d061ec&id=6067&cid=5965

---

## 主题四：科大讯飞与高校合作案例（2024–2026，公开报道）

### 4.1 2024 年

| 时间 | 高校 | 合作内容 |
|---|---|---|
| 2024-06-19 | 信阳学院 | 人工智能现代产业学院揭牌（双方自 2018 年起共建大数据与 AI 教学实验中心） |
| 2024-09-18 | 南通大学 | 首届人工智能班开班，"政-产-学-研-创"合作，3+1 培养模式，讯飞技术总监任企业导师 |
| 2024-09-27 | 长沙商贸旅游职业技术学院 | 与科大讯飞、麒麟软件共建人工智能产业学院、麒麟信创产业学院 |
| 2024-10-10 | 浙江农林大学暨阳学院 | 校政企（诸暨经开区）三方共建讯飞人工智能产业学院，首届招 180 人，设教学、企业工坊、科研、产业赋能四大中心 |
| 2024-10-18 | 重庆第二师范学院 | 战略合作，共建"儿童领域大模型""教师教育大脑"、多模态儿童智能教育研究中心 |
| 2024-10-24 | 辽宁轨道交通职业学院 | 签约暨人工智能产业学院揭牌；全国首家与讯飞合作 AI 通识课教育与专业能力图谱建设的高职院校 |

### 4.2 2025 年

| 时间 | 高校 | 合作内容 |
|---|---|---|
| 2025-04-09 | 山东师范大学 | 战略合作，共建"AI+"心理健康联合实验室、高等教育数字化升级、基础教育大模型"智思体" |
| 2025-04-29 | 山东大学 | 战略合作，揭牌**"星火"人工智能联合实验室**与**教育创新智能体孵化应用基地**，覆盖智慧校园/智慧教学/人才培养/科技创新 |
| 2025-05-21 | 安徽师范大学+安徽信息工程学院（三方） | 联合成立**"AI+高等教育研究院"**，覆盖 AI+人才培养/科研/教学/智慧校园/产业孵化五大领域 |
| 2025-06 | 安徽大学 | 战略合作，共建智能科学与技术学科，覆盖人才交流、科学研究、智慧教学、平台建设、成果转化、智慧校园 |
| 2025-06 | 四川财经职业学院 | 围绕数据治理中台、星火校园百事通等开展智慧校园建设交流 |
| 2025-07-04 | 广州南方学院 | 共建人工智能产业学院 + 研究生联合培养基地（该校首个落户企业的研究生基地） |
| 2025-09-04 | 南京财经大学 | 共建**人工智能前沿交叉学院**，"AI+人才/教学/科研/校园"四大方向 |
| 2025-09-20 | 中国科学技术大学 | 签署人工智能科技英才班协议，共建培养方案、课程与实践教学，设专项基金（此前已共建语音及语言信息处理国家工程研究中心、认知智能全国重点实验室） |
| 2025-09-27 | 兰州大学信息学院 | 战略合作交流，探讨实习实训基地、联合申报科研项目；讯飞研究院副院长受聘行业导师 |
| 2025-01-13/2026-01 | 南京晓庄学院 | 战略合作，共建人工智能学科专业群、"AI+教育"实践教学平台、未成年人心理咨询大模型 |

### 4.3 2026 年

| 时间 | 高校 | 合作内容 |
|---|---|---|
| 2026-01-14 | 外交学院 | 战略合作框架协议：外交语料库、外交领域专属大模型、共建联合实验室、人才培养实践基地 |
| 2026-01-20 | 西安汽车职业大学 | 签署人工智能产业学院合作协议，聚焦智能网联汽车人才培养 |
| 2026-01-25 | 武汉理工大学艺术与设计学院 | 共建智能体验设计联合创新中心 |
| 2026-03-27 | 云南民族大学 | 签约暨联合标注中心启用，共建"云南省民族多语种智能融合与应用国际联合实验室"、民族语言标准数据集、"AI+新文科" |
| 2026-05-27 | 天津师范大学 | 战略合作（刘庆峰出席）：基础教育智能学科大模型研发、共建高水平智慧教育联合实验室，未来五年人才联合培养/科研协同/特色学科共建/公共服务共享 |
| 2026-06-24 | 河北美术学院 | 以星火大模型为支撑共建 AIGC 艺术创作实验室，工程师驻校授课 |
| 2026-07-03 | 安徽信息工程学院 | 与讯飞教育技术研究院共建**皖江智能教育研究院** |
| 2026-09-06 | 中国石油大学（北京） | 克拉玛依校区揭牌"讯飞人工智能产业学院"，聚焦"AI+能源" |
| 2026-04 | 华南师范大学 | 教育人工智能研究院主办、讯飞教育 BG 协办第一届"星火杯"教育智能体设计大赛 |

### 4.4 与国创赛产业命题赛道的直接关联（本项目最相关）

- 科大讯飞是**中国国际大学生创新大赛产业命题赛道的命题企业/组织方**，赛道负责人为科大讯飞产教融合生态总监、创新创业总监吴然，获教育部"优秀企业组织奖"；命题方向强调"AI+真实痛点"、技术编码与需求解码双向融合。
- 获奖案例：大连理工大学"知汛常安"项目揭榜科大讯飞"AI 赋能下的智慧水利"命题，获第十届国创赛产业赛道全国总决赛**银奖**（已应用于松辽水利委员会防洪会商）。
- 讯飞依托其共建的**讯飞现代产业学院**体系（如安徽中医药大学）组织产业命题赛道项目评审，并在长沙理工大学、信阳学院、赣南师范大学、河南农业经济学院、西电、浙机电等校开展赛道培训。
- "星火杯"：面向全球大学生的国家级赛事（共青团中央与教育部双认证），累计覆盖全球 21 国、953 所院校、5200+ 支团队；2026 年第四届为智能体创新赛道（基于讯飞星辰 Agent 平台），总奖池 25 万元，提供星辰 MaaS 88 元调用额度等资源。

**主题四来源 URL**：
- https://edu.iflytek.com/about-us/news/company-news/2077.html （山东大学）
- https://www.view.sdu.edu.cn/info/1003/201763.htm
- https://edu.iflytek.com/about-us/news/company-news/2111.html （AI+高等教育研究院）
- https://ahnu.edu.cn/info/1108/136690.htm
- http://ah.people.com.cn/n2/2025/0521/c227131-41235025.html
- https://edu.iflytek.com/about-us/news/company-news/2007 （山东师范大学）
- https://edu.iflytek.com/about-us/news/company-news/2229.html （安徽大学）
- https://edu.iflytek.com/about-us/news/company-news/1519.html （暨阳学院产业学院）
- http://news.ustc.edu.cn/info/1055/92761.htm （中国科大）
- https://zsb.ustc.edu.cn/2025/1124/c35498a711231/page.htm
- https://www.eol.cn/guangdong/gdgd/202507/t20250705_2679199.shtml （广州南方学院）
- https://www.toutiao.com/article/7550601848651006510/ （南京财经大学）
- http://zk.zjol.com.cn/zx/202509/t20250904_31211447.shtml
- https://xxxy.lzu.edu.cn/xueyuanxinwen/keyan/2025/1010/319733.html （兰州大学）
- https://www.njxzc.edu.cn/25/d7/c3561a140759/page.htm （南京晓庄学院）
- https://www.cque.edu.cn/dwhzc/info/1085/1642.htm （重庆第二师范学院）
- http://m.jyb.cn/rmtzcg/xwy/wzxw/202410/t20241024_2111261014_wap.html （辽宁轨道交通职业学院）
- https://www.eol.cn/henan/hengd/202409/t20240910_2632072.shtml （信阳学院）
- https://www.jsenews.com/news/gx/202409/t20240924_8399183.shtml （南通大学）
- https://www.hn.chinanews.com.cn/news/shyw/2024/0927/498847.html （长沙商贸旅游职院）
- https://www.ymu.edu.cn/info/1151/77931.htm （云南民族大学）
- https://hzjlc.tjnu.edu.cn/info/1096/1707.htm （天津师范大学）
- https://zs.cfau.edu.cn/xydt/2212e1a3812e472988d9c724020d8595.htm （外交学院）
- http://a-d.whut.edu.cn/xyxw/202603/t20260302_624128.shtml （武汉理工）
- https://www.hbafa.edu.cn/info/1023/7063.htm （河北美院）
- https://www.eol.cn/anhui/ahgd/202607/t20260707_2753102.shtml （安信工皖江智能教育研究院）
- http://m.sxjybk.com/2026/0122/129417.html （西安汽车职业大学）
- https://m.thepaper.cn/newsDetail_forward_34043587 （中国石油大学（北京））
- http://aied.scnu.edu.cn/a/20260421/791.html （华南师大星火杯）
- https://www.ahtcm.edu.cn/info/1731/496121.htm ；https://wap.ahtcm.edu.cn/info/1731/481521.htm （讯飞现代产业学院评审）
- https://sche.dlut.edu.cn/info/1404/34510.htm （大连理工银奖案例）
- https://www.csust.edu.cn/cxcyjyxy/info/1128/3907.htm （长沙理工培训）
- https://www.xyxun.com/section-3-752496-0.html （信阳学院讲座）
- https://www.gnnu.edu.cn/info/1004/180821.htm （赣南师大 2026 产业赛道师资培训）
- https://ie.xidian.edu.cn/sczx/xwdt/51.htm （西电）
- https://baike.baidu.com/item/%E6%98%9F%E7%81%AB%E6%9D%AF%E5%A4%A7%E6%A8%A1%E5%9E%8B%E5%BA%94%E7%94%A8%E5%88%9B%E6%96%B0%E8%B5%9B/67772084
- https://www.wenda.edu.cn/wy/display_1214.html

---

## 附：对项目书"合作模式"章节的建议要点

1. **以"产业命题赛道揭榜者"身份定位与讯飞的关系**：项目书应明确本团队是揭榜科大讯飞命题的参赛团队，而非泛泛的校企合作申请方；可援引大连理工"知汛常安"揭榜讯飞命题获国赛产业赛道银奖的案例，说明揭榜路径可行、讯飞命题关注"AI+真实痛点"（来源见主题四 4.4）。
2. **技术合作抓手：星火 API 全栈接入**。承诺产品技术栈基于讯飞开放平台（OpenAI 兼容接口 `https://spark-api-open.xf-yun.com/v1`，Spark Lite 免费 + Pro 每月 400 万 tokens 免费额度足够支撑开发、演示与初阶运营），写明已规划的应用申请与实名认证流程，体现"真的能接、马上能跑"。
3. **强调大学段补位价值**：用财报证据（讯飞高教产品仅"讯飞AI课程"一项、投入约 1576 万元，远低于 K12 各项；智学网不覆盖高校）论证讯飞在高等教育段相对薄弱，本项目面向高校学习场景可成为其大学段生态的增量场景，对讯飞有独特互补价值——这是合作叙事中最有力的一条。
4. **对齐讯飞既有高校合作范式，提出可落地的合作形式菜单**：援引 2024–2026 案例，提出分层合作方案——轻量：接入星火 API+联合课程/赛事（对标"星火杯"教育智能体大赛、华南师大模式）；中期：共建联合实验室或应用孵化基地（对标山东大学"星火"人工智能联合实验室、教育创新智能体孵化应用基地）；远期：共建产业学院/研究院（对标南财人工智能前沿交叉学院、安师大"AI+高等教育研究院"）。
5. **捆绑赛事资源**：项目书可写明计划参加/依托"星火杯"（2026 智能体创新赛道，提供星辰 MaaS 88 元调用额度与星火 API 资源）与国创赛产业赛道双通道，说明团队能持续获得讯飞官方资源扶持，降低合作方投入成本。
6. **风险与合规表述**：注明免费额度政策存在调整可能（如 Max 已于 2026-03 下线）、QPS=2 的免费限制下的降级策略（Lite 打底、按量付费 Pro/Ultra 扩容），以及密钥管理、实名认证等合规动作——体现团队对讯飞政策的熟悉程度，增强可信度。
7. **突出国产自主可控叙事**：讯飞官方强调"全栈自主可控国产教育大模型"与全国产算力训练（星火 X1/X2），项目书可将"基于国产大模型的教育应用"作为响应国家 AI 战略的亮点，与讯飞官方口径同频。
8. **预留对接通道**：写明拟通过讯飞产业命题赛道负责人/产教融合团队（吴然等）及 1024 开发者节、开发者大赛官网（challenge.xfyun.cn）等公开渠道建立联系，使"合作模式"章节有明确可执行的下一步动作。

---

## 来源统计

- 主题一（API 接入方式）：18 个来源 URL（官方文档 5 + 教程/开源实现 13）
- 主题二（免费额度政策）：15 个来源 URL
- 主题三（智学网与智慧教育生态）：21 个来源 URL
- 主题四（高校合作案例）：37 个来源 URL
- 合计：约 91 个来源条目（部分 URL 在主题间复用）

**未查到公开信息的事项**：讯飞开放平台针对高校学生的独立"校园认证/学生专属免费额度"政策（仅有面向参赛大学生的"星火杯"资源扶持）；智学网覆盖高校的可靠证据（结论为不覆盖）；讯飞教育业务中 K12 与高校的官方细分收入占比（仅能通过研发投入对比佐证）。
