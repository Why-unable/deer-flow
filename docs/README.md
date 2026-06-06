# DeerFlow Docs 索引

本目录保存 DeerFlow 当前分支的部署说明、MMKB 集成记录、设计审查、历史改动
总结、实施计划与验证证据。

## MMKB 集成与部署

| 文档 | 简介 |
|---|---|
| [`deploy.md`](./deploy.md) | MMKB 集成版 DeerFlow 的最简 Docker 部署流程，包括环境变量、内部认证检查和启动命令。 |
| [`MMKB_INTEGRATION_CHANGES.md`](./MMKB_INTEGRATION_CHANGES.md) | 当前分支为接入 MMKB 所做的完整改动说明，是后续开发、审查和同步上游时的主要依据。 |
| [`MMKB_AGENT_OUTPUT_COMPARISON.md`](./MMKB_AGENT_OUTPUT_COMPARISON.md) | 对比 DeerFlow 自带前端与 MMKB OpenAI 兼容 Agent Mode 的输出、展示能力和设计取舍。 |

## Agent 与 Skill 审查

| 文档 | 简介 |
|---|---|
| [`RESEARCH_AGENT_GENERALITY_REVIEW.md`](./RESEARCH_AGENT_GENERALITY_REVIEW.md) | 审查 `research-analyst` 对本地知识库的偏好是否削弱通用 Agent 能力，并记录后续改进方向。 |
| [`SKILL_NAME_CONFLICT_FIX.md`](./SKILL_NAME_CONFLICT_FIX.md) | 记录 public skill 与 custom skill 同名冲突问题、已有分析和待处理状态。 |

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
- 调整 `research-analyst`、RAG 使用策略或 Skill 白名单：先读
  [`RESEARCH_AGENT_GENERALITY_REVIEW.md`](./RESEARCH_AGENT_GENERALITY_REVIEW.md)。
- 历史计划和 diff 总结可能已经过时，实施前应以当前代码为准重新核对。

