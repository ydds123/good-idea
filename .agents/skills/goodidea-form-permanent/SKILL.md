---
name: goodidea-form-permanent
description: "通过一次一个问题的苏格拉底式对话，帮助用户澄清其 Good idea 永久、母题、行动或索引卡片观点；允许从用户内容中忠实提炼标题，但正文判断必须来自用户。用户主动发起卡片、口述想法或提交草稿时使用。"
---

# 接收用户永久卡片草稿

永久卡片只能由用户主动发起。Agent 可以从用户表达中提炼标题，并通过苏格拉底式对话帮助用户完善判断，但不能替用户生成正文观点。

## 不可越过的作者边界

- 可以从用户已经表达的中心判断中提炼一个典型标题；标题不得加入用户没有表达的新主张。
- 不替用户写中心主张、理由、例子、边界、反例、行动或结论。
- 不把 Agent 的推断、反例、连接建议或审查意见放进草稿。
- 不润色、重排或补全用户原文，也不提供一份可直接替换用户草稿的改写稿。
- 用户只有一个想法时，进入苏格拉底式交流；每轮只问一个最关键的问题，根据用户上一轮回答继续追问，不一次抛出问题清单，也不替用户回答。
- 对话中的零散表达不是可发布正文。观点澄清后仍需取得用户确认的最终正文；在此之前不调用写命令。
- 四种类型 permanent、mother、action、index 都遵守同一作者边界。

## 流程

1. 确认卡片由用户主动发起。若用户给出的是口述想法，先交给 `goodidea-review-permanent` 做一次一个问题的苏格拉底式澄清。
2. 根据用户完整表达提炼标题，不要求用户另行命名；可以展示标题，但不得借标题引入新主张。
3. 取得用户确认的最终正文。正文全部来自用户，不含 Frontmatter；若用户自行提供 `# 标题`，沿用用户标题。
4. 审查通过且用户明确要求正式创建后，把最终正文保存到仓库外临时文件。Agent 提炼标题时调用：

       uv run goodidea --root <仓库> permanent propose --type <permanent|mother|action|index> --title <提炼标题> --draft-file <用户正文临时文件> --source-ids <ID列表> --from-ids <ID列表>
       uv run goodidea --root <仓库> permanent accept --proposal-id <ID> --confirm-user-authored

   用户自带标题时省略 `--title`，草稿第一行必须是唯一的 `# 标题`。
5. 运行 `uv run goodidea --root <仓库> verify`。比对正式卡片正文：除提炼标题、CRLF/CR 统一为 LF、补末尾换行外，正文必须与用户确认内容一致。

`permanent propose` 只允许提炼标题，不授权 Agent 创作正文候选。错误或过时的待处理草稿用 `permanent withdraw` 撤销，不能接纳。

正式卡片创建后的 `permanent revise` 和 `permanent feedback` 也只能提交用户亲自写下的内容，并带 `--confirm-user-authored`；CLI 可以机械添加区块、列表标记和时间戳、规范化边界换行，但不得改变用户措辞。Agent 仍然只能评估，不能维护正文。
