---
name: goodidea-form-permanent
description: "仅在用户明确主动发起 Good idea 永久、母题、行动或索引卡片后，通过一次一个问题的苏格拉底式对话澄清并形成待确认草稿。普通口述想法、进行中的闪念捕获及“以后可以成卡”不触发本 Skill。"
---

# 接收用户永久卡片草稿

永久卡片只能由用户主动发起。Agent 可以通过苏格拉底式对话帮助用户完善判断；用户授权后，可以结构化用户表达，但不能新增观点。

## 不可越过的作者边界

- 可以从用户已经表达的中心判断中提炼一个典型标题；标题不得加入用户没有表达的新主张。
- 不替用户创造中心主张、理由、例子、边界、反例、行动或结论。
- 不把 Agent 的推断、反例、连接建议或审查意见放进草稿。
- 只有用户明确授权后，才可删除口语停顿与重复、调整已有表达顺序并整理成 Markdown；不得补入用户未表达的内容。
- 必须把结构化后的完整草稿展示给用户。用户未明确确认整份草稿时，禁止持久化。
- 用户只有一个想法时，进入苏格拉底式交流；每轮只问一个最关键的问题，根据用户上一轮回答继续追问，不一次抛出问题清单，也不替用户回答。
- 对话中的零散表达不是可发布正文。观点澄清后形成待确认草稿；在用户确认全文之前不调用写命令。
- 四种类型 permanent、mother、action、index 都遵守同一作者边界。

## 流程

1. 确认卡片由用户主动发起。若用户给出的是口述想法，先交给 `goodidea-review-permanent` 做一次一个问题的苏格拉底式澄清。
2. 根据用户完整表达提炼标题，并把用户已表达的内容结构化为 Markdown；只删除口语噪声、合并重复和调整顺序，不新增观点。
3. 展示完整待确认草稿。只有用户明确确认全文没有问题，才把它视为最终草稿。
4. 用户明确要求正式创建后，把最终草稿保存到仓库外临时文件并调用：

       uv run goodidea --root <仓库> permanent propose --type <permanent|mother|action|index> --draft-file <确认后的完整草稿> --confirm-user-approved-structure --source-ids <ID列表> --from-ids <ID列表>
       uv run goodidea --root <仓库> permanent accept --proposal-id <ID> --confirm-user-approved

   用户直接提交自己的完整草稿时仍可使用旧的逐字模式；草稿第一行必须是唯一的 `# 标题`。
5. 运行 `uv run goodidea --root <仓库> verify`。正式卡片正文除行尾规范化外，必须与用户确认的结构化草稿一致。

`permanent propose` 不授权 Agent 创作新观点。错误或过时的待处理草稿用 `permanent withdraw` 撤销，不能接纳。

正式卡片创建后的 `permanent revise` 和 `permanent feedback` 也只能提交用户亲自写下的内容，并带 `--confirm-user-authored`；CLI 可以机械添加区块、列表标记和时间戳、规范化边界换行，但不得改变用户措辞。Agent 仍然只能评估，不能维护正文。
