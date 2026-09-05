# DeerFlow Docs 索引

本目录保存 DeerFlow 当前分支的部署说明、MMKB 集成记录、设计审查、历史改动
总结、实施计划与验证证据。

## 核心机制与配置

| 文档 | 简介 |
|---|---|
| [`MEMORY_IMPLEMENTATION.md`](./MEMORY_IMPLEMENTATION.md) | 说明 DeerFlow 长期记忆模块的数据流、消息筛选、LLM 提取、按用户/Agent 隔离、存储和注入机制。 |
| [`CONFIG_YAML_REFERENCE.md`](./CONFIG_YAML_REFERENCE.md) | 规范化介绍 `config.yaml` 的加载规则、全部主要配置段、字段语义和运行边界。 |

## MMKB 集成与部署

| 文档 | 简介 |
|---|---|
| [`deploy.md`](./deploy.md) | MMKB 集成版 DeerFlow 的最简 Docker 部署流程，包括环境变量、内部认证检查和启动命令。 |
| [`MMKB_INTEGRATION_CHANGES.md`](./MMKB_INTEGRATION_CHANGES.md) | 当前分支为接入 MMKB 所做的完整改动说明，是后续开发、审查和同步上游时的主要依据。 |
| [`MMKB_AGENT_OUTPUT_COMPARISON.md`](./MMKB_AGENT_OUTPUT_COMPARISON.md) | 对比 DeerFlow 自带前端与 MMKB OpenAI 兼容 Agent Mode 的输出、展示能力和设计取舍。 |
| [`MMKB_AGENT_STORAGE_AND_OOM_TROUBLESHOOTING.md`](./MMKB_AGENT_STORAGE_AND_OOM_TROUBLESHOOTING.md) | 说明存储配置边界，并记录公网 Agent SSE 未正常结束、后台 run 持续执行和服务器 OOM 的风险分析、取证命令及分阶段修复建议。 |
| [`MMKB_URL_LIFECYCLE.md`](./MMKB_URL_LIFECYCLE.md) | 说明 MMKB RAG URL 从工具响应、签名与绝对化，到最终 Agent 正文和 artifact 下载的完整生命周期及校验边界。 |
| [`../../mmkb/docs/LINK_DELIVERY.md`](../../mmkb/docs/LINK_DELIVERY.md) | 说明 MMKB RAG/Agent 模式中的来源文档、签名图片/视频和 DeerFlow artifact 下载链接机制。该文件位于同级 MMKB 项目。 |

## Agent 与 Skill 审查

| 文档 | 简介 |
|---|---|
| [`RESEARCH_AGENT_GENERALITY_REVIEW.md`](./RESEARCH_AGENT_GENERALITY_REVIEW.md) | 审查 `research-analyst` 对本地知识库的偏好是否削弱通用 Agent 能力，并记录普通任务、本地知识问答和系统综述的建议边界。 |
| [`DEEP_RESEARCH_USAGE_LOGIC.md`](./DEEP_RESEARCH_USAGE_LOGIC.md) | 整合主流产品和开源研究 Agent 的 Deep Research 触发逻辑，并对照说明 `local-deep-research` 与 `local-systematic-literature-review` 的当前边界、潜在冲突和改进方向。 |
| [`SKILL_NAME_CONFLICT_FIX.md`](./SKILL_NAME_CONFLICT_FIX.md) | 记录 public skill 与 custom skill 同名冲突问题、已有分析和待处理状态。 |

当前 RAG 工具选择规则已经在 Agent、Skill 和工具描述中对齐：

- 普通本地知识主题查询默认从 `rag_search` 开始；
- 证据充分的轻量问答可直接回答，不强制执行完整研究流程或生成报告文件；
- `rag_list_documents` 用于文档清单、范围发现和多文档综述候选池，不作为普通主题查询的固定前置步骤；
- 明确要求多文档筛选、跨文档综合或系统综述时，使用 `local-systematic-literature-review` 的 inventory-first 流程；
- SOUL 只要求选择最短且充分的检索路径，不固定具体 RAG 工具顺序，以保留 Agent 通用性。

## 历史改动记录

| 文档 | 简介 |
|---|---|
| [`CODE_CHANGE_SUMMARY_BY_FILE.md`](./CODE_CHANGE_SUMMARY_BY_FILE.md) | 按文件和 diff 汇总某次代码改动，适合追溯历史变更；内容可能不代表当前完整实现。 |

## 实施计划与设计规格

| 路径 | 简介 |
|---|---|
| [`plans/2026-04-01-langfuse-tracing.md`](./plans/2026-04-01-langfuse-tracing.md) | 可选 Langfuse tracing 支持的实施计划。 |
| [`superpowers/plans/2026-04-10-event-store-history.md`](./superpowers/plans/2026-04-10-event-store-history.md) | 使用 append-only event store 恢复完整 thread history 的后端兼容层计划。 |
| [`superpowers/specs/2026-04-11-runjournal-history-evaluation.md`](./superpowers/specs/2026-04-11-runjournal-history-evaluation.md) | 使用 RunJournal / event store 替代 checkpoint history messages 的方案评估。 |
| [`superpowers/specs/2026-04-11-summarize-marker-design.md`](./superpowers/specs/2026-04-11-summarize-marker-design.md) | 在历史记录中展示 summarization 标记的设计与验证说明。 |

## 优化提升方向

| 文档 | 简介 |
|---|---|
| [`optimization/README.md`](./optimization/README.md) | 记录当前 MMKB 集成版 DeerFlow 的后续工程优化方向。 |
| [`optimization/MMKB_VISUAL_ASSET_BRIDGE.md`](./optimization/MMKB_VISUAL_ASSET_BRIDGE.md) | 规划将 MMKB 图片按需下载到 DeerFlow sandbox，并复用 `view_image` 完成视觉模型分析。 |

## 验证证据

`pr-evidence/` 保存用于 PR 或功能验证的截图：

- `session-skill-manage-e2e-20260406-202745.png`
- `skill-manage-e2e-20260406-194030.png`

这些文件用于证明特定版本的界面或端到端行为，不应作为当前实现说明的唯一
依据。

## 阅读建议

- 部署 MMKB 集成版：先读 [`deploy.md`](./deploy.md)。
- 了解当前 MMKB 适配：先读
  [`MMKB_INTEGRATION_CHANGES.md`](./MMKB_INTEGRATION_CHANGES.md)。
- 调整 Agent 输出转换：同时阅读
  [`MMKB_AGENT_OUTPUT_COMPARISON.md`](./MMKB_AGENT_OUTPUT_COMPARISON.md)。
- 排查 RAG 文档、媒体或 artifact 链接：先读
  [`MMKB_URL_LIFECYCLE.md`](./MMKB_URL_LIFECYCLE.md)，再结合 MMKB 项目的
  [`LINK_DELIVERY.md`](../../mmkb/docs/LINK_DELIVERY.md)。
- 了解存储配置，或排查 Agent 回复后客户端持续转圈、服务器 OOM：阅读
  [`MMKB_AGENT_STORAGE_AND_OOM_TROUBLESHOOTING.md`](./MMKB_AGENT_STORAGE_AND_OOM_TROUBLESHOOTING.md)。
- 调整 `research-analyst`、RAG 使用策略或 Skill 白名单：先读
  [`RESEARCH_AGENT_GENERALITY_REVIEW.md`](./RESEARCH_AGENT_GENERALITY_REVIEW.md)，
  如涉及 deep research 触发边界，再读
  [`DEEP_RESEARCH_USAGE_LOGIC.md`](./DEEP_RESEARCH_USAGE_LOGIC.md)，
  并对照 [`MMKB_INTEGRATION_CHANGES.md`](./MMKB_INTEGRATION_CHANGES.md) 中记录的
  当前已实施行为。
- 历史计划和 diff 总结可能已经过时，实施前应以当前代码为准重新核对。
