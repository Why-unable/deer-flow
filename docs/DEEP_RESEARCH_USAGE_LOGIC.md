# Deep Research 使用逻辑与本地 Skill 路由

## 文档目的

本文整合主流产品和开源研究 Agent 对 Deep Research 的使用逻辑，并对照
DeerFlow 当前 `research-analyst` 的两个本地研究 skill：

- `skills/custom/local-deep-research/SKILL.md`
- `skills/custom/local-systematic-literature-review/SKILL.md`

目标是明确：

- 用户什么情况下应触发 deep research；
- 当前 `local-deep-research` 的触发逻辑是什么；
- 它是否需要继续改进；
- 它与 `local-systematic-literature-review` 是否冲突。

## 外部产品与开源库的共同模式

不同产品名称不同，但 Deep Research 通常不是由关键词 `deep research`
本身触发，而是由任务形态触发。

### ChatGPT Deep Research

OpenAI Help Center 将 Deep Research 定义为适合多步骤或深入问题，
尤其是需要跨多个来源聚合和综合时使用。快速查找和短对话应使用普通 chat。

OpenAI 公开介绍还强调 Deep Research 会搜索、解释、分析文本、图片和 PDF，
并生成带引用的完整报告，适合金融、科学、政策、工程和需要大量资料综合的
专业任务。

参考：

- <https://help.openai.com/en/articles/10500283-deep-research-in-chatgpt>
- <https://openai.com/index/introducing-deep-research/>

### Gemini Deep Research

Gemini Deep Research 面向复杂研究任务：先拆解问题，探索网页、
Workspace 内容或用户提供的文件，再综合为完整结果。Gemini API 文档把
Deep Research Agent 描述为会自主规划、执行和综合多步骤研究任务，并生成
详细、有引用的报告。

参考：

- <https://gemini.google/overview/deep-research/>
- <https://ai.google.dev/gemini-api/docs/interactions/deep-research>

### Claude Research

Claude Research 面向需要搜索和分析信息的复杂问题。它会围绕问题自动探索
不同角度、检索来源并综合结果。它的定位也更接近研究报告或复杂调研，而不是
普通事实问答。

参考：

- <https://support.claude.com/en/articles/11088861-use-research-on-claude>

### GPT Researcher

GPT Researcher 是开源 deep research agent，目标是为任意研究任务收集多源
可信信息，并生成 deep research report。它强调研究过程、来源聚合和报告
交付，而不是单轮问答。

参考：

- <https://github.com/assafelovic/gpt-researcher>
- <https://gptr.dev/>

### LangChain Open Deep Research / Deep Agents

LangChain 相关实现将 deep research 明确拆成 scope、research、write 等
阶段，使用计划、子任务、来源跟踪和最终报告综合。它强调复杂问题的多轮
搜索、评估、引用和写作。

参考：

- <https://www.langchain.com/blog/open-deep-research>
- <https://docs.langchain.com/oss/python/deepagents/deep-research>

## 可归纳的触发条件

从上述产品和开源库看，Deep Research 适合以下任务。

### 应触发 Deep Research

| 用户意图 | 原因 |
|---|---|
| 多步骤复杂问题 | 需要拆成多个子问题检索、分析和综合。 |
| 多来源综合 | 答案依赖多个网页、论文、报告、PDF、Workspace 文件或本地文档。 |
| 明确要求报告 | 用户目标是研究报告、调研报告、完整分析报告，而不是聊天回答。 |
| literature review / survey / SLR | 需要文献筛选、统一字段抽取、跨文档主题综合。 |
| competitive / market / policy / industry research | 通常需要多来源、趋势、对比和证据。 |
| 趋势、共识、分歧、缺口分析 | 需要从多份资料中抽取和综合模式。 |
| 用户要求 citations、evidence matrix、纳入/排除标准 | 这是研究工作流，而不是普通问答。 |
| 问题开放且边界宽 | 需要探索信息空间，而不是查一个确定事实。 |

### 不应触发 Deep Research

| 用户意图 | 更合适的处理 |
|---|---|
| 简单事实查询 | 普通回答或一次检索。 |
| 单篇文档总结 | 单文档阅读/摘要。 |
| 明确概念解释 | 普通回答或轻量 RAG。 |
| “有哪些文档” | 文档清单工具，不需要研究流程。 |
| 小范围问答 | `rag_search` + 必要的 preview/chunks。 |
| 写作、润色、翻译、代码问题 | 普通 Agent 能力，除非用户要求基于本地证据。 |

## DeerFlow 当前路由模型

当前 `research-analyst` 采用三层判断。

### 普通任务

不依赖本地知识库、也不需要外部多源研究的任务，不应触发本地研究 skill。
例如：

- 普通聊天；
- 代码问答；
- 文本润色；
- 翻译；
- 不依赖本地文档的概念解释。

### 本地普通研究：`local-deep-research`

当前 `local-deep-research` 的 frontmatter 和正文定义是：

- 当用户需要基于本地知识库回答一个具体问题；
- 解释一个主题；
- 分析某个概念、系统或文档集；
- 生成基于本地证据的普通研究回答；
- 任务重点是回答一个具体问题，而不是构建多文档综述集合。

它的轻量路径是：

1. 默认先使用一次 `rag_search(query="<topic>", mode="hybrid", limit=10)`；
2. 如果命中的 chunks/assets 足以支撑回答，直接综合；
3. 只有上下文不足、需要精确证据或涉及视觉细节时，才继续读
   preview/chunks/assets；
4. 不把 `rag_list_documents` 作为普通主题查询的固定前置步骤；
5. 除非用户明确要求报告、文件或可下载交付物，否则直接在聊天正文回答。

典型请求：

| 请求 | 是否适合 `local-deep-research` |
|---|---|
| “NIST 文档讲了什么？” | 适合，通常是具体文档/主题解释。 |
| “解释本地文档里的 CSF 2.0” | 适合。 |
| “这些资料中某概念是什么意思？” | 适合。 |
| “基于本地文档回答这个具体问题” | 适合。 |
| “从本地文档生成一段摘要/建议” | 适合，若不是多文档综述报告。 |

### 本地系统综述：`local-systematic-literature-review`

当前 `local-systematic-literature-review` 已扩展为处理：

- 深度研究报告；
- 完整研究报告；
- 基于本地全部文档或所有相关文档的报告；
- 研究趋势；
- 主题综合；
- 系统性文献综述、survey、literature review、SLR；
- annotated bibliography；
- 多篇论文、报告、标准或白皮书的跨文档方法比较；
- 纳入/排除筛选和证据矩阵。

典型请求：

| 请求 | 是否适合 `local-systematic-literature-review` |
|---|---|
| “基于本地全部文档做深度研究报告” | 适合。 |
| “综合所有相关文档生成完整研究报告” | 适合。 |
| “比较这些论文的方法、发现和局限” | 适合。 |
| “分析本地文档中的研究趋势、共识和缺口” | 适合。 |
| “做一个 systematic literature review / survey” | 适合。 |

## 当前 `local-deep-research` 是否可以改进

可以继续改进，但不建议把它改成完整报告型 deep research。它应保留为
“本地普通深度回答” skill，而不是和系统综述 skill 合并。

### 1. 触发描述仍偏宽

当前 `local-deep-research` 仍包含：

- `what is X`
- `explain X`
- `research X`
- 用户只给出一个宽泛主题

这些表达在普通聊天里也很常见。如果 Agent 没有先判断“本地知识库是否是主要
证据源”，可能仍会过度触发本地研究流程。

改进方向：

- 强调只有当任务已经进入“本地知识任务模式”时，才加载
  `local-deep-research`；
- 普通概念解释不要仅因出现 `explain` 或 `what is` 就触发本地 RAG；
- 本地证据无关或用户明确要通用知识时，应直接回答或使用网页/官方来源。

### 2. “普通研究回答”和“报告生成”边界还可以更硬

当前 skill 已经要求完整研究报告转向 `local-systematic-literature-review`。
但“生成基于本地证据的普通研究回答”仍可能被模型理解为报告生成。

改进方向：

- 在 `local-deep-research` 中明确：若用户要求文件交付、完整报告、全部文档、
  多文档综合、趋势和证据矩阵，应立即转向 `local-systematic-literature-review`；
- 若用户只要求“回答/解释/总结”，则保持聊天正文回答，不默认写文件。

### 3. 可以补充决策表

当前规则散落在描述、适用场景和不适用场景中。可以在
`local-deep-research` 中补一张简短决策表：

| 判断问题 | 是 | 否 |
|---|---|---|
| 是否明确依赖本地知识库？ | 继续判断 | 不触发本地 skill |
| 是否要求多文档筛选/综合/趋势/报告？ | 转 SLR | 继续判断 |
| 是否是具体问题或主题解释？ | 使用 `local-deep-research` | 直接回答或澄清 |
| 一次 `rag_search` 是否足够？ | 轻量回答 | 深入 preview/chunks/assets |

这比单纯增加长段提示更容易被模型执行。

## 是否与综述 Skill 冲突

当前设计下，两者不应冲突；它们是上下游边界关系。

| 维度 | `local-deep-research` | `local-systematic-literature-review` |
|---|---|---|
| 目标 | 回答具体问题、解释主题、普通本地分析 | 生成多文档综述或完整研究报告 |
| 检索方式 | 以 `rag_search` 为默认入口 | `rag_list_documents` + 多组 `rag_search` |
| 文档范围 | 一个主题下的相关证据 | 候选池、纳入/排除、文档集合 |
| 证据组织 | 关键证据支撑回答 | 统一字段抽取和 evidence matrix |
| 输出 | 聊天正文为主，必要时文件 | 完整 Markdown 报告 + `present_files` |
| 子代理 | 仅复杂独立维度时使用 | 多文档批量抽取时优先使用 |
| 完成标准 | 充分回答具体问题 | plan、screening、extraction、synthesis、quality check |

潜在冲突只来自“触发词重叠”：

- “deep research” 字面上可能让模型选择 `local-deep-research`；
- 但“深度研究报告 / 完整研究报告 / 全部文档 / 所有相关文档 / 研究趋势 /
  主题综合”在产品语义上属于多来源研究报告，应选择
  `local-systematic-literature-review`。

当前 SOUL 和两个 skill 已经把这个优先级写清楚：多文档报告型请求优先
进入 `local-systematic-literature-review`，`local-deep-research` 负责具体
问题的深度回答。

## 推荐最终路由规则

可以把用户请求按以下顺序判断：

1. **是否与本地知识库有关？**
   - 否：不触发本地 research skill。
   - 是：继续。

2. **是否要求完整报告、多文档综合、全部文档、趋势、综述、证据矩阵？**
   - 是：触发 `local-systematic-literature-review`。
   - 否：继续。

3. **是否是具体问题、主题解释、单篇/少量文档总结或普通本地分析？**
   - 是：触发 `local-deep-research` 或直接使用轻量 RAG。
   - 否：澄清范围。

4. **是否证据已经足够？**
   - 是：直接回答。
   - 否：继续 preview/chunks/assets 或有限网页补充。

## 结论

Deep Research 的核心触发条件不是“用户说了 deep research”，而是：

- 多步骤；
- 多来源；
- 需要筛选和综合；
- 需要报告交付；
- 需要引用、证据矩阵或可追溯来源；
- 问题开放且范围宽。

对 DeerFlow 来说，`local-deep-research` 不应承担完整研究报告职责。
它适合本地证据支持下的具体问题深度回答。完整报告、多文档综述、趋势和
证据矩阵应由 `local-systematic-literature-review` 处理。
