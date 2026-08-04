---
name: goodidea-form-permanent
description: "接收用户亲自写成的 Good idea 永久、母题、行动或索引卡片草稿，并在审查通过且用户明确要求正式创建后原样提交。用户主动发起创建永久卡片或提供自己的完整草稿时使用；禁止代写、改写、润色或补全内容。"
---

# 接收用户永久卡片草稿

永久卡片只能由用户主动发起并亲自写成。这里的“形成”是组织提交与创建流程，不是替用户生成内容。

## 不可越过的作者边界

- 不替用户写标题、中心主张、理由、例子、边界、反例、行动或结论。
- 不把 Agent 的推断、反例、连接建议或审查意见放进草稿。
- 不润色、重排或补全用户原文，也不提供一份可直接替换用户草稿的改写稿。
- 用户只有一个想法而没有完整草稿时，说明卡片标准并请用户自己写；此时不调用写命令。需要暂存原始想法时，只能在用户同意后改用 `goodidea-capture-flash`。
- 四种类型 permanent、mother、action、index 都遵守同一作者边界。

## 流程

1. 确认创建永久卡片是用户主动提出的，并取得用户完整 Markdown 草稿。草稿第一行内容必须是唯一的 `# 标题`，正文全部是用户原话，不含 Frontmatter。
2. 把原文草稿交给 `goodidea-review-permanent` 审查。审查只指出问题，不修改草稿。
3. 若有缺陷，等待用户自行修改后重新审查。用户没有明确要求正式创建时，不写仓库。
4. 审查通过且用户明确要求正式创建后，把用户最终原文保存到仓库外的临时 Markdown 文件，依次调用：

       uv run goodidea --root <仓库> permanent propose --type <permanent|mother|action|index> --draft-file <用户原文临时文件> --source-ids <ID列表> --from-ids <ID列表>
       uv run goodidea --root <仓库> permanent accept --proposal-id <ID> --confirm-user-authored

5. 运行 `uv run goodidea --root <仓库> verify`，比对正式卡片正文与用户最终草稿。允许的唯一规范化是把 CRLF/CR 行尾统一为 LF 并补末尾换行；CLI 添加的 Frontmatter、索引、日志和 Git 提交不属于正文改写。

`permanent propose` 只是提交用户草稿，不授权 Agent 创作候选。错误或过时的待处理草稿用 `permanent withdraw` 撤销，不能接纳。

正式卡片创建后的 `permanent revise` 和 `permanent feedback` 也只能提交用户亲自写下的内容，并带 `--confirm-user-authored`；CLI 可以机械添加区块、列表标记和时间戳、规范化边界换行，但不得改变用户措辞。Agent 仍然只能评估，不能维护正文。
