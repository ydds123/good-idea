---
name: goodidea-lint
description: "巡检 Good idea Markdown 卡片网络。用户要求检查、验证、健康审计、查断链、快照篡改、状态或索引问题时使用；默认只报告，不在未获授权时修改内容或自动接受认知候选。"
---

# 巡检 Good idea

先运行只读检查：

    uv run goodidea --root <仓库> lint

需要交付级验证时运行：

    uv run goodidea --root <仓库> verify

## 报告顺序

1. 快照哈希异常、路径越界或符号链接风险；
2. 缺失 Frontmatter、类型与目录不符、重复 ID；
3. 断链、来源账本失效、索引不一致，以及正式内容残留的旧 `summary` 字段；
4. Git 工作区是否干净；
5. 孤立、矛盾、长期未行动等需要人工判断的认知健康提示。

默认不修复。机械问题获授权后可由 CLI 重建索引或更新格式；旧 `summary` 字段只能通过 `goodidea maintain metadata` 机械移除。语义连接、永久卡片接纳、判断修正仍须用户参与。任何快照哈希异常都应立即停止其他写入。

来源文件只允许“原文快照 → 关联闪念”。若发现旧版文献笔记层，报告结构错误；空占位可由 `goodidea maintain sources` 删除，实际内容必须先由用户决定是否迁移为闪念，不能静默丢弃。
