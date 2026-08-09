# Good idea Skill 路由评测

- 状态：`static_passed`
- 证据类型：`static_description_scan`
- Skill：`7`
- 场景案例：`46`
- description 指纹：`7908cbe23594713aac49e295af698a16c0d32c5ea6a61aeb88651f16dc1f1ce6`

## 证据边界

静态扫描只说明 description 文本是否高度重叠。模型批量评测会逐条分类真实中文请求，但不是 Codex 原生 Skill 激活遥测，也不等同于每个案例单独启动一次完整任务。
多个 Skill 只在不同阶段顺序交接时属于正常协作；争夺同一阶段才算冲突。

## 静态重叠

- 阈值：`0.55`
- 未声明的高重叠：`0`
- 已声明的高重叠：`0`

| Skill A | Skill B | 相似度 | 解释 |
|---|---|---:|---|
| `goodidea-form-permanent` | `goodidea-review-permanent` | 0.331 | intentional_handoff：形成卡片是入口和写入所有者，审查卡片是苏格拉底式澄清阶段；同一请求可以顺序交接，但不能同时拥有写入。 |
| `goodidea-capture-flash` | `goodidea-record-literature` | 0.219 | — |
| `goodidea-lint` | `goodidea-record-literature` | 0.166 | — |
| `goodidea-connect-cards` | `goodidea-lint` | 0.145 | — |
| `goodidea-record-literature` | `goodidea-review-permanent` | 0.140 | — |
| `goodidea-capture-flash` | `goodidea-review-process` | 0.136 | — |
| `goodidea-capture-flash` | `goodidea-lint` | 0.133 | — |

## 重点覆盖的语义风险场景

- **high · permanent-entry-cluster** · `goodidea-capture-flash` / `goodidea-form-permanent` / `goodidea-review-permanent`：口述想法和草稿是共享名词；没有明确永久卡片意图时必须只由 capture 接管，form 与 review 还要按形成动作和评估动作分开。
- **medium · network-membership-vs-semantic-edge** · `goodidea-connect-cards` / `goodidea-lint`：检查卡片是否存在于永久空间、索引和账本属于 lint；只有寻找或确认支持、冲突、限定、例证等语义边才属于 connect。
- **medium · linked-source-vs-unlinked-note** · `goodidea-capture-flash` / `goodidea-record-literature`：当前捕获阶段和用户认知意图优先于附件类型；想法附带 URL/Markdown/TXT 仍由 capture 主导，只有纯来源保存和捕获后的后台维护由 record-literature 处理。
- **medium · content-review-vs-structural-lint** · `goodidea-review-process` / `goodidea-lint`：逐条让用户判断中间材料去向属于 review-process；只读检查结构、快照、索引、账本和 Git 属于 lint。

## 重点覆盖的召回风险场景

- `goodidea-form-permanent`：description 可能没有充分覆盖“为正式卡片追加用户本人修订或行动反馈”。

## 模型路由结果

本次只运行静态扫描，缺少模型路由证据。
