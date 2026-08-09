# Good idea Skill 路由评测

- 状态：`passed`
- 证据类型：`model_backed_batch_classifier`
- Skill：`7`
- 场景案例：`41`
- description 指纹：`a5b055ab519f92a69af465fe5a8faaeea9ea245fbf59d53a5025cef7e9bf24bb`

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
| `goodidea-lint` | `goodidea-record-literature` | 0.237 | — |
| `goodidea-capture-flash` | `goodidea-review-process` | 0.209 | — |
| `goodidea-lint` | `goodidea-review-permanent` | 0.208 | — |
| `goodidea-record-literature` | `goodidea-review-permanent` | 0.202 | — |
| `goodidea-form-permanent` | `goodidea-record-literature` | 0.195 | — |
| `goodidea-form-permanent` | `goodidea-lint` | 0.174 | — |

## 重点覆盖的语义风险场景

- **high · permanent-entry-cluster** · `goodidea-capture-flash` / `goodidea-form-permanent` / `goodidea-review-permanent`：口述想法和草稿是共享名词；没有明确永久卡片意图时必须只由 capture 接管，form 与 review 还要按形成动作和评估动作分开。
- **medium · network-membership-vs-semantic-edge** · `goodidea-connect-cards` / `goodidea-lint`：检查卡片是否存在于永久空间、索引和账本属于 lint；只有寻找或确认支持、冲突、限定、例证等语义边才属于 connect。
- **medium · linked-source-vs-unlinked-note** · `goodidea-capture-flash` / `goodidea-record-literature`：record-literature 当前只能处理可访问 URL 的来源快照；无链接报告摘录和明确不保存的网页不应触发来源写入。
- **medium · content-review-vs-structural-lint** · `goodidea-review-process` / `goodidea-lint`：逐条让用户判断中间材料去向属于 review-process；只读检查结构、快照、索引、账本和 Git 属于 lint。

## 重点覆盖的召回风险场景

- `goodidea-record-literature`：description 可能没有充分覆盖“刷新或更新已经保存的网页来源”。
- `goodidea-form-permanent`：description 可能没有充分覆盖“为正式卡片追加用户本人修订或行动反馈”。

## 模型路由结果

- 通过：`41/41`
- 失败：`0`
- 模型判断为冲突：`0`
- 模型：`gpt-5.6-sol`

| 路由 | 通过 | 总数 | 通过率 |
|---|---:|---:|---:|
| `goodidea-capture-flash` | 6 | 6 | 1.000 |
| `goodidea-connect-cards` | 4 | 4 | 1.000 |
| `goodidea-form-permanent` | 4 | 4 | 1.000 |
| `goodidea-lint` | 6 | 6 | 1.000 |
| `goodidea-record-literature` | 5 | 5 | 1.000 |
| `goodidea-review-permanent` | 5 | 5 | 1.000 |
| `goodidea-review-process` | 5 | 5 | 1.000 |
| `no_route` | 6 | 6 | 1.000 |

## 失败案例

无。
