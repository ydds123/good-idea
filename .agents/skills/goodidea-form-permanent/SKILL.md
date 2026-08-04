---
name: goodidea-form-permanent
description: "从闪念、来源、有意思案例或行动经验形成 Good idea 永久卡片候选。用户希望沉淀认识、形成母题、记录可复盘行动或建立索引入口时使用；只生成候选，不绕过用户解释门禁。"
---

# 形成永久卡片候选

先读相关中间材料、来源原文和已有卡片。区分作者陈述、事实、用户理解与 Agent 推断。

## 形成候选

1. 选择 permanent、mother、action 或 index。
2. 保持一个中心主张。若包含多个独立判断，先拆分候选。
3. 写清理由、条件、边界、反例以及来源 ID；Agent 推论只作为候选，不伪装成用户立场。
4. 调用：

       uv run goodidea --root <仓库> permanent propose --type <类型> --title <标题> --claim <中心内容> --reason <理由> --boundaries <边界> --source-ids <ID列表> --from-ids <ID列表>

   行动卡还要提供 context、judgment、action；结果未知时保持待反馈。
5. 把候选交给 goodidea-review-permanent。不要直接接受候选。

候选只能位于隐藏的 proposals 目录，尚未属于永久空间。

