# Good idea Skill 路由评测

- 状态：`static_passed`
- 证据类型：`static_description_scan`
- Skill：`7`
- 场景案例：`43`
- description 指纹：`c48f1bb7aaa622f4131a3ead1e6229929f152e7bd186794fd99e54f143d183ee`

## 证据边界

静态扫描只说明 description 文本是否高度重叠。模型批量评测会逐条分类真实中文请求，但不是 Codex 原生 Skill 激活遥测，也不等同于每个案例单独启动一次完整任务。
多个 Skill 只在不同阶段顺序交接时属于正常协作；争夺同一阶段才算冲突。

## 静态重叠

- 阈值：`0.55`
- 未声明的高重叠：`0`
- 已声明的高重叠：`1`

| Skill A | Skill B | 相似度 | 解释 |
|---|---|---:|---|
| `goodidea-form-permanent` | `goodidea-review-permanent` | 0.675 | intentional_handoff：形成卡片是入口和写入所有者，审查卡片是苏格拉底式澄清阶段；同一请求可以顺序交接，但不能同时拥有写入。 |
| `goodidea-capture-flash` | `goodidea-record-literature` | 0.224 | — |
| `goodidea-capture-flash` | `goodidea-review-process` | 0.209 | — |
| `goodidea-lint` | `goodidea-review-permanent` | 0.208 | — |
| `goodidea-form-permanent` | `goodidea-lint` | 0.174 | — |
| `goodidea-lint` | `goodidea-record-literature` | 0.155 | — |
| `goodidea-record-literature` | `goodidea-review-permanent` | 0.149 | — |

## 重点覆盖的语义风险场景

- **high · permanent-entry-cluster** · `goodidea-capture-flash` / `goodidea-form-permanent` / `goodidea-review-permanent`：口述想法和草稿是共享名词；没有明确永久卡片意图时必须只由 capture 接管，form 与 review 还要按形成动作和评估动作分开。
- **medium · network-membership-vs-semantic-edge** · `goodidea-connect-cards` / `goodidea-lint`：检查卡片是否存在于永久空间、索引和账本属于 lint；只有寻找或确认支持、冲突、限定、例证等语义边才属于 connect。
- **medium · linked-source-vs-unlinked-note** · `goodidea-capture-flash` / `goodidea-record-literature`：可访问 URL 和用户明确要作为来源的外部 Markdown/TXT 应由 record-literature 处理；随手粘贴的无链接摘录属于 capture，只读网页和本地 PDF 不应触发来源写入。
- **medium · content-review-vs-structural-lint** · `goodidea-review-process` / `goodidea-lint`：逐条让用户判断中间材料去向属于 review-process；只读检查结构、快照、索引、账本和 Git 属于 lint。

## 重点覆盖的召回风险场景

- `goodidea-form-permanent`：description 可能没有充分覆盖“为正式卡片追加用户本人修订或行动反馈”。

## 模型路由结果

本次只运行静态扫描，缺少模型路由证据。
