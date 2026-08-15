# Good idea v0.1 Schema

本文件只定义 CLI 可以校验的数据结构、状态转换、命令门禁和事务不变量。人的作者权以 `AGENTS.md` 为最高规则；具体对话方式由项目 Skills 维护；`README.md` 只负责解释。发现冲突时停止写入并先同步规则、实现和测试。

## 目录与类型

| 目录 | `type` | 允许状态 |
|---|---|---|
| `闪念空间/` | `闪念` | `待处理`, `已处理`, `已放弃` |
| `溯源空间/` | `来源` | `完整`, `部分抓取`, `抓取失败`, `有更新待确认` |
| `有意思空间/` | `有意思` | `待处理`, `已处理`, `已放弃` |
| `待办空间/` | `待办` | `未开始`, `进行中`, `已过期`, `已完成`, `已取消` |

待办按状态归档（2026-08-15 用户拍板，v2 扩展）：`待办空间/` 根目录存放行动清单（`未开始` + `进行中`）；`待办空间/已过期/` 存放 `已过期`；`待办空间/已完成/` 存放 `已完成`；`待办空间/已取消/` 存放 `已取消`。`capture transition` 流转状态时自动把卡片文件移到对应状态目录（`已过期`/`已完成`/`已取消` 移入子目录，改回 `未开始`/`进行中` 移回根目录），并同步重写全库引用、索引与状态账本。所有扫描（lint/verify/review/maintain/find_note）同时覆盖根目录与三个状态子目录，归档卡片不脱离系统管理。

48h 行动窗口（2026-08-15 用户拍板）：新建待办默认 `未开始` 并在 frontmatter 记录 `not_started_at`（最近一次进入未开始的时刻，CLI 维护：创建/重新承诺时写入，退出未开始时清除）。`capture sweep` 确定性扫描：`未开始` 且 `now - not_started_at >= 48h` → 转 `已过期` 并归档（无过期项不产生事务；`not_started_at` 缺失的存量卡跳过并报告）。48h 是开始行动的窗口而非完成期限；`进行中` 不参与窗口。已过期裁决：transition 回 `未开始`（重新承诺，重新计时）或 `已取消`（干掉）。

闪念按状态归档（2026-08-15 用户拍板，与待办同构）：`闪念空间/` 根目录存放 `待处理` 闪念；`闪念空间/发酵中/` 存放 `发酵中`（讨论裁决不转但留档等待激发点的中间态——不转 ≠ 无价值 ≠ 处理完；可被永久卡素材检索捞取，激发后由 `permanent accept` 自动转 `已处理`）；`闪念空间/已处理/` 存放 `已处理`。`permanent accept` 接纳永久卡时把形成来源闪念（`待处理` 或 `发酵中`）自动标为 `已处理` 并移入子目录；`capture transition` 对闪念开放 `待处理`/`发酵中`/`已处理`/`已放弃` 流转（`已放弃` 暂无归档目录，文件保持原位）；`capture sync` 批量归位阅读层手动改状态后的闪念。全库扫描（lint/verify/review/maintain/find_note/索引）同时覆盖根目录与 `发酵中/`、`已处理/` 子目录，归档卡片不脱离系统管理。

阅读层手动修改是合法输入（2026-08-15 用户拍板）：Obsidian 数据库视图（note-database）内直接改 `status` 只写回 frontmatter（字符串可能被写成裸 YAML 标量），不移动文件、不更新索引账本。CLI 两条收口路径：① `capture transition --accept-dirty` 把目标文件当前内容视为用户意图，完成规范化、归档移动与聚焦提交；② `capture sync` 扫描待办（根/已过期/已完成/已取消）与闪念（根/已处理）归档目录，一次事务归位所有"状态 ≠ 所在目录"的记录（状态值无法识别的跳过并报告，不阻塞其余）。frontmatter 解析器兼容裸 YAML 标量值（字符串/数字/布尔/空），数组与对象仍要求 JSON 风格。

捕获会话讨论存档（2026-08-15 用户拍板）：捕获会话的 entries 同时支持 `role=user`（用户口述，进入正式闪念候选）与 `role=assistant`（Agent 输出，仅作讨论记录入档，不重置 proposal、不进入正式追溯）；`completed-captures/` 会话存档**永久保留**（`capture cleanup` 只清后台维护临时缓存，不删会话——讨论原文是认知资产）；finalize 落卡时 frontmatter 写入 `capture_session`，卡片可回溯到自己的讨论过程存档，讨论可延续而非重新开始。`capture discuss` 提供围绕既有卡片的讨论原文记录：按时间线（`role=user\|assistant` + 时间戳）追加到 `.goodidea/runtime/discussions/<id>.json`（Git 忽略内部层），卡片 frontmatter 写 `discussion_log` 关联——**只记录原文，不转化、不结构化摘要**；转/不转永久卡都保留，未转时原文仍挂在卡片下。

待办估价（2026-08-15 用户拍板，目标规划方法论五段流程的落盘命令）：`capture valuate` 为待办写入七个语义标签——`need_type`（需求类型：自主/能力/归属，**固定 3 种**）、`goal_id`（高阶目标：认知中枢/行业职业/创作能力/工具效能，见 GOAL_SPECS，**受控库**——估价先匹配现有目标，Agent 发现覆盖不了的新方向只能列候选等用户确认，不得自行发明；新增目标走契约扩展）、`equifinality`/`multifinality`/`success_probability`（等效性/多效性/成功概率：高/中/低）、`distance`（目标距离：近/中/远）、`specificity`（具体性：具体/模糊）——覆盖方法论六特征。标签由 Agent 按方法论判断（语义层）并给出逐条理由，CLI 校验枚举合法性并确定性重算行动清单（`未开始`+`进行中`）待办的 `priority`（**期望×价值×距离**排序：概率×多效性×距离主键、等效性 tie-break、未估价排最后按创建时间；`已过期`/`已完成`/`已取消` 不参与估价），一次事务完成标签写入与全局重排。理由写入卡片"估价依据"区（对象|内容|说明 三列 Markdown 表格，CLI 机械维护，含确定性得分与优先级；`--rationale` 必填，机制不接受黑箱估价）。标签写回卡片 frontmatter（中文值，Obsidian 数据库视图按 priority 排序、标签列下拉单选）；每 8 小时 cron（0/8/16 点）自动估价新增待办（估价前先做状态检查：事实已完成/失效的先归档；顺带运行 `capture sweep` 执行 48h 过期扫描）。估价前先读卡片"## 为什么做"区（摄入澄清写入的用户动机原话）作为判断依据。
| `永久空间/永久卡片/` | `永久卡` | `有效`, `已修订`, `已停用` |
| `永久空间/母题卡片/` | `母题` | `进行中`, `演化中`, `已停用` |
| `永久空间/行动卡片/` | `行动` | `待行动`, `行动中`, `待观察`, `已复盘` |
| `永久空间/索引卡片/` | `索引` | `有效`, `已修订`, `已停用` |

所有正式内容必须包含 JSON-compatible YAML Frontmatter：

| 字段 | 必需性 | 约束 |
|---|---|---|
| `id` | 必需 | 稳定且全仓库唯一 |
| `type` | 必需 | 必须与所在目录对应 |
| `title` | 必需 | 同时用于一级标题和人类可读文件名 |
| `status` | 必需 | 必须属于该类型的允许状态 |
| `created_at` | 必需 | 创建后保持不变，ISO 8601 本地时间 |
| `updated_at` | 必需 | 每次正式状态或内容变化时更新 |

正式内容 Frontmatter 禁止 `summary`。Git 事务记录中的 `summary` 是操作说明，只进入 `.goodidea/state.json`、`log.md` 和提交信息，不属于卡片元数据。

## 稳定 ID

- 闪念：`FLA-YYYYMMDD-xxxxxxxx`
- 来源：`SRC-xxxxxxxxxxxx`。网页由规范化 URL 决定；本地文档由首次导入的 `origin_sha256` 决定，状态账本键为 `local:sha256:<origin_sha256>`。两者遇到同一来源都稳定复用。
- 有意思：`INT-YYYYMMDD-xxxxxxxx`
- 待办：`TODO-YYYYMMDD-xxxxxxxx`
- 永久/母题/行动/索引：`PER|MOT|ACT|IDX-YYYYMMDD-xxxxxxxx`
- 直接表达形成见证：`WIT-xxxxxxxxxxxx`
- 提案：`PRP-xxxxxxxxxxxx`

调用方可以提供 `--transaction-id`。同一事务 ID 重放必须返回原结果且不再创建文件或 Git 提交。

ID 是系统内部的稳定身份，用于去重、状态关联、来源关系、事务审计和标题变更后的对象识别。ID 不属于标题，也不得出现在内容文件名或生成式索引中。

## 人类可读文件名

五个空间中的所有内容文件统一使用 `YYYY-MM-DD-标题.md`，日期取 `created_at` 的本地创建日期。文件名冲突时在标题后机械追加 `-2`、`-3`；不得用 ID 解决冲突。标题和文件名可以面向人调整，内部 ID 保持不变。

现有文件通过 `goodidea maintain filenames` 原子重命名。该事务同时维护路径链接、事务结果、索引、日志和 Git 历史。

## 内部参数

Markdown Frontmatter 是 CLI 的机器控制面，不是阅读正文。Obsidian 默认显示属性，方便用户查看卡片身份、状态、时间和来源关系；这些字段仍只能由 CLI 维护，不应在 Obsidian 中手工修改。

### 枚举值中文化（2026-08-11 契约）

正式内容 Frontmatter 中的语义枚举值使用中文（`type`：`闪念`/`来源`/`有意思`/`待办`/`永久卡`/`母题`/`行动`/`索引`；`status`、`capture_status`、`authoring_mode` 同理，完整映射见 `src/goodidea/contracts.py` 的 `ENUM_ZH`）。CLI 在读写边界做双向归一化：读取时中文值归一化为英文内部值，写入时英文内部值本地化为中文，状态机、校验与事务逻辑始终运行在英文内部值上。字段名（`type`、`status` 等）、ID、哈希与时间戳保持英文机器格式不变。内部状态（捕获会话、维护任务、候选文件、可读性检查）不进正式 Frontmatter，保持英文。

| 参数 | 中文含义 | 系统用途 |
|---|---|---|
| `id` / `type` | 稳定身份 / 对象类型 | 在改名后仍识别同一对象，并校验所在空间 |
| `title` | 标题 | 生成文件名、一级标题和人类可读链接别名 |
| `status` | 生命周期状态 | 区分待处理、已失效、完整、待行动等状态 |
| `created_at` / `updated_at` | 创建 / 更新时间 | 文件命名、排序和演化审计 |
| `source_ids` / `derived_from` | 外部依据 / 形成关系 | `source_ids` 只引用外部来源；普通永久卡片的 `derived_from` 至少引用一个真实形成来源；反向可读链接由 CLI 生成 |
| `canonical_url` | 规范链接 | 网页来源的点击、身份和去重；原始分享链接不持久化 |
| `origin_filename` / `origin_sha256` | 原文件名 / 首次导入内容哈希 | 本地来源的人类可读来处和稳定身份；不依赖本机路径 |
| `capture_status` / `fetched_at` | 获取结果 / 获取时间 | 判断快照是否完整及何时取得 |
| `content_sha256` / `snapshot_sha256` | 内容 / 快照哈希 | 检测来源变化并阻止原文快照被静默篡改 |
| `image_failures` | 图片保存失败记录 | 明确标记不完整来源，避免静默依赖远程图片 |
| `tags` | 来源渠道标签 | 仅来源层的可选回忆锚点（用户命名的高辨识度实体身份专有名词：渠道品牌/人物/系列场景）；弱约束：多值字符串列表、不进枚举机制；全中文、去重由对话层查重维护，不做 lint 校验，数量由对话层与用户商定 |

这些参数只能由 CLI 维护。需要排查问题时再查看 `schema.md` 和 `.goodidea/state.json`，不要把它们当成卡片正文。

### 各类型字段

| 类型 | 额外必需字段 | 条件或可选字段 |
|---|---|---|
| `闪念` | `source_ids` | 形成正式卡片后可转为 `已处理` |
| `有意思` | `source_ids` | 无 |
| `待办` | `source_ids` | 无 |
| `source` | `capture_status`、`fetched_at`、`content_sha256`、`snapshot_sha256`、`image_failures`；网页另必须有 `canonical_url`，本地文档另必须有 `origin_filename` 和 `origin_sha256` | `author`、`published_at`、`tags`（来源渠道标签，见内部参数字段表）、存在更新候选时的 `pending_update` |
| `永久卡` | `authoring_mode`、`source_ids`、`derived_from`、`formation_draft_sha256` | `derived_from` 不得为空 |
| `母题`、`行动`、`索引` | `authoring_mode`、`source_ids`、`derived_from` | 无 |

`source_ids` 与 `derived_from` 必须是 ID 列表。`source_ids` 只表示外部来源提供的依据；`derived_from` 表示这张卡实际从哪些材料或表达中形成。普通永久卡片的形成来源可以是闪念、外部来源、既有正式材料或直接表达形成见证；同一外部来源可以同时出现在两个列表中，但角色不同。母题、行动、索引卡片没有关系时仍使用空列表。来源正文中的“关联闪念”是由闪念 `source_ids` 生成的人类可读反向视图，来源 Frontmatter 不重复保存 `flash_ids`。闪念是否陈旧在回顾时按 `created_at + 48 小时`动态计算，不持久化过期时间或自动改写状态。`capture_status` 只表示当前快照的获取质量，取值为 `完整`、`部分抓取` 或 `抓取失败`；来源存在更新候选时，生命周期 `status` 可以是 `有更新待确认`，原获取质量仍由 `capture_status` 保留。

网页身份和本地文档身份严格二选一：网页来源不得出现 `origin_filename` / `origin_sha256`；本地来源不得出现 `canonical_url`。`origin_filename` 只保存 basename，禁止持久化绝对路径；`origin_sha256` 是 64 位小写十六进制哈希，作为首次导入身份，后续刷新不改写。同一内容的文件被移动或复制后仍复用同一来源；内容发生变化时必须对既有来源执行 `source refresh`，不得当作新来源静默导入。

`authoring_mode` 只能是：

- `用户原文`（user_verbatim）：用户直接提交完整原文草稿；
- `仅提炼标题`（user_body_agent_title）：Agent 只从用户正文提炼标题；
- `用户确认·Agent结构化`（user_confirmed_agent_structured）：Agent 只整理用户已表达内容，且用户确认了完整结构化草稿。

### 内部候选文件

候选文件位于 `.goodidea/proposals/`，不属于五个正式内容空间，也不进入人类可读索引。

| 候选类型 | Frontmatter 额外字段 | 账本与正文不变量 |
|---|---|---|
| `permanent_proposal` | `card_type`、`authoring_mode`、`draft_sha256`、`source_ids`、`from_ids`；普通永久卡片另需 `formation_sources_confirmed`，直接表达时另需 `direct_source_anchor`、`direct_source_sha256` | 候选文件本身是唯一事实源；草稿正文哈希必须与 Frontmatter 一致；旧候选不会被静默补齐新确认 |
| `source_update_proposal` | 无 | 正文机器负载保存来源 ID、旧/新内容哈希和预览 |
| `connection_proposal` | 无 | 正文机器负载保存起点、终点、关系和理由 |

候选目录只保存 `pending` 文件。接纳或撤销后删除候选；结果与原因保留在事务账本、追加日志和 Git 历史中，不再维护终态候选文件或 `state.json.proposals` 镜像。来源身份直接由来源文件的规范身份字段和稳定 ID 决定，不再维护 `state.json.sources` 镜像。

正式永久卡片草稿正文不得出现内部负载或“机器数据”区块。来源更新和连接候选的机器负载只存在于隐藏候选目录，由 CLI 校验和读取。

### 直接表达形成见证

`.goodidea/formation-witnesses/<WIT-ID>.md` 只在普通永久卡片直接形成于本轮表达、又没有可寻址对象可以代表这次形成情境时创建。它是内部来源见证，不是第五种正式卡片，也不进入 `index.md`、生命周期、回顾或语义连接流程。

见证必须包含 `id`、固定 `type: formation_witness`、`title`、`created_at`、`card_id`、`proposal_id`、`draft_sha256` 和 `source_anchor_sha256`。正文只保存用户确认的一句形成情境和指向正式卡片的机械反链；不得保存完整聊天原文。普通永久卡片通过 `derived_from` 指回见证，并由 CLI 在正文末尾机械添加“形成来源”导航区。该导航区不属于用户确认的认知正文，不能由 Agent 自由改写。

## Obsidian 产品基线

`.obsidian/app.json`、`appearance.json`、`core-plugins.json` 和 `snippets/goodidea.css`、`snippets/properties-zh.css` 属于 v0.1 产品基线：默认显示 Frontmatter 属性（显示层中文映射与账本字段隐藏见 properties-zh.css）、隐藏内部目录、自动维护链接，并把附件保存到 `assets/`。`workspace.json` 只记录本机临时窗口状态，不进入 Git。

## 溯源文件

每份来源是单一 Markdown 文件，结构固定：

```markdown
---
...来源元数据...
---
# 标题

## 原文快照
<!-- goodidea:snapshot:start sha256=<hash> -->
...作者、日期、正文、本地图片...
<!-- goodidea:snapshot:end -->

## 关联闪念
```

标题直接使用来源名称。原文快照紧随标题，关联闪念位于原文之后。网页只永久保存规范链接，不保留带分享或追踪参数的原始链接；外部本地文档只接受 UTF-8 `.md`、`.markdown` 和 `.txt`，不保存绝对路径或伪造链接。导入 Markdown 时，开头 YAML Frontmatter 只用于提取允许的来源元数据，随后从正文快照移除；与最终来源标题相同（仅空白或引号等排版标点差异视为相同）的开头一级标题也机械移除，避免在正式来源标题下重复显示。正文开头已自带作者/来源与发布/日期信息头时，CLI 不再重复插入作者与发布日期上下文行。除此之外保持正文内容和顺序。v0.1 不接受本地 PDF 作为来源快照。

溯源空间只保存外部世界说过什么，不设置文献笔记层。用户看到来源时产生的观点、疑问或念头进入闪念空间；用户连接并思考多个念头后形成的判断进入永久空间。关联闪念区只由 CLI 机械维护导航关系，不承载新的解释内容。

哈希基于两个快照标记之间规范化后的完整文本。Frontmatter 和起始标记中的哈希必须相同。任何写操作开始前都要校验所有来源快照；发现异常则停止。

来源图片（包括网页图片和本地 Markdown 的相对图片）存入 `assets/<内容哈希>.<扩展名>`，正文使用库内相对链接。下载或读取失败时以明确的失败占位文本替换原图片，来源状态降为 `部分抓取`，不让可读性静默依赖远程图片或原本地路径。

## 状态机与命令门禁

### 临时捕获会话

`.goodidea/runtime/captures/<session-id>/` 是 Git 忽略的运行时防丢区，不属于五个内容空间。每个会话只以 `session.json` 保存角色明确的顺序记录、上下文可访问性/轻量指纹和最新闪念候选；不得再维护 transcript、context 或 proposal 镜像文件，也不得进入 `index.md`、正式 `log.md` 或 Git。

捕获状态为 `active`、`reviewing`、`paused`、`confirmed`、`finalized` 或 `abandoned`。新增用户表达会使旧候选和旧确认失效；finalize 只接受最新候选内容哈希和用户完成确认。一次会话可以原子生成零张、一张或多张正式闪念。临时会话写入只执行路径、锁、格式和幂等校验，不扫描来源快照。

新候选 manifest 使用 `format_version: 2`。每张闪念以一次“认知激活事件”为单位，可以包含多个逻辑相关内容，但必须同时保存：`body`（去除口语噪声后的完整脉络）、`trigger_anchor`（现实背景、现象、卡点与情绪）和 `activated_logic`（内容在当时如何连起来）。有外部上下文时，`source_anchors` 必须为每个 `context_ref` 提供一条 `explanation`；后台来源维护把它渲染为同一个“可点击溯源链接 + 论证说明”单元，跨来源归因限制可写入 `source_boundary`。没有外部上下文时才使用纯文本 `source_anchor` 明确说明“用户本轮口述，无外部来源”。正式闪念不得再另设只含链接的“关联来源”节。`entry_ids` 必须全部指向用户表达；这些字段只允许忠实整理，不允许补造。旧运行时候选按 v1 完成，不强制补写或伪造缺失锚点。

正式闪念的 `created_at` 取其最早相关用户表达时间，`updated_at` 取正式生成时间。finalize 成功后运行时会话进入短期恢复区；来源维护完成且至少经过 24 小时后才可清理。用户放弃则不创建正式内容并删除临时会话。

finalize 同时创建可恢复的运行时维护任务。任务允许 `pending`、`processing`、`maintenance_paused`、`retry_pending`、`partial`、`failed`、`complete`、`cancelled` 或 `context_changed`。来源处理失败不得回滚正式闪念。

### 可执行状态转换

| 类型 | 创建状态 | CLI 可以执行的转换 |
|---|---|---|
| `闪念` | `待处理` | `capture transition` 可设为 `待处理`、`已放弃`；`已处理` 由系统在正式卡片接纳时自动设置（并归档到 `闪念空间/已处理/`），不开放手动流转；陈旧仅为回顾时的动态标记 |
| `有意思` | `待处理` | `capture transition` 可设为 `待处理`、`已处理`、`已放弃` |
| `待办` | `未开始` | `capture transition` 可设为 `未开始`、`进行中`、`已过期`、`已完成`、`已取消`（目标文件已有阅读层手动修改时加 `--accept-dirty`；`capture sync` 批量收口手动修改；`capture sweep` 确定性把超 48h 未开始转 `已过期`） |
| `来源` | 当前抓取质量对应 `完整`、`部分抓取` 或 `抓取失败` | `source refresh` 生成候选：当前状态 `→ 有更新待确认`；接受候选：`有更新待确认 →` 新快照抓取质量 |
| `永久卡`、`索引` | `有效` | `permanent revise` 可设为 `有效`、`已修订` 或 `已停用`；未指定时转为 `已修订` |
| `母题` | `进行中` | `permanent revise` 可设为 `进行中`、`演化中` 或 `已停用`；未指定时转为 `演化中` |
| `行动` | `待行动` | `permanent revise` 可设为 `待行动`、`行动中`、`待观察` 或 `已复盘`；未指定时转为 `待观察`；`permanent feedback` 转为 `已复盘` |

表中的保留状态是数据模型允许但当前 CLI 尚未暴露转换入口的状态，不能靠手工编辑 Frontmatter 进入。新增入口必须同时修改本表、实现和测试。

### 命令前置条件

| 命令 | 必须满足 |
|---|---|
| `source preview` | `--url` 和 `--local-file` 二选一；本地文档限 UTF-8 `.md` / `.markdown` / `.txt`。只在仓库外生成临时预览，对 Good idea 仓库零写入 |
| `source commit` | 必须提供有实际内容的用户保存动机；纯确认文本无效 |
| `capture start/append` | 只写运行时会话；同一幂等键不得重复记录；不运行来源、索引、Git 或全库验证 |
| `capture propose` | 候选只能引用会话中存在的用户表达；v2 必须带来源、触发和激活逻辑锚点；新版本取代旧版本但不创建正式闪念 |
| `capture finalize` | 必须确认最新候选覆盖本轮内容；候选之后没有新表达；一次原子生成多张闪念并创建后台任务 |
| `capture revise-source-anchors` | 必须引用闪念已有的全部来源、逐项说明论证作用，并带用户修正确认；机械合并来源与论证锚点 |
| `capture maintenance-check` | 比较当前上下文与讨论时指纹；变化时原子转为 `context_changed` |
| `capture maintenance-update` | 维护任务暂停、恢复、失败或完成；重试最多三次，耗尽后转为 `failed` |
| `capture cleanup` | 仅清理维护已终结且超过 24 小时的 Git 忽略完成会话 |
| `capture pause/resume/discard` | pause/resume 不改变正式内容；discard 必须有用户放弃确认并产生零正式写入 |
| `source commit --attach-flash-ids` | 只关联已经存在的正式闪念，不额外创建保存动机闪念；必须由维护任务提供逐卡论证说明，或显式提供 `--anchor-explanation` |
| `source commit --attach-flash-ids --maintenance-job-id` | 按任务缓存成功图片，重试不重复下载；提交后自动回写 `complete` 或 `partial` |
| `source refresh` | 网页和本地来源都先创建候选并保留旧快照；本地更新必须显式指定既有来源。接受时要求仍为同一个待处理候选且旧哈希一致 |
| `permanent propose` | 输入必须是用户确认后的完整草稿；结构化模式还必须带显式结构确认；普通永久卡片必须带 `--confirm-user-approved-sources`，并通过 `--from-ids` 提供至少一个可寻址形成来源，或通过 `--direct-source-file` 提供用户确认的一句具体形成情境；`--source-ids` 只表示外部依据，不能单独满足形成门禁；候选进入隐藏目录，不进入永久空间。带 `--preauthorize-accept` 时，用户在确认草稿的同时已明确授权正式创建；propose 校验通过后同一调用内继续执行 accept 的全部校验（候选与草稿哈希一致、形成来源可寻址、状态为 `pending`）并直接创建正式卡片，候选不残留；除创建确认的时机提前外，所有既有门禁照常必需 |
| `permanent accept` | 候选、Frontmatter、正文哈希和状态账本必须一致且状态为 `pending`，并带用户在候选形成后的明确创建确认；普通永久卡片原子创建卡片及必要的直接表达见证、维护形成来源导航、删除候选，并只把 `待处理` 形成闪念转为 `已处理`；`已处理` 保持不变，`已放弃` 拒绝接纳。`permanent propose --preauthorize-accept` 提供的授权等价于本确认，仅时机提前到草稿确认时；两种路径下的 accept 校验完全一致 |
| `permanent withdraw` | 只撤销仍为 `pending` 的候选；撤销后不可接纳，错误内容不保留在当前工作树 |
| `permanent revise` / `permanent feedback` | 只能追加用户亲自提供并确认的内容；CLI 只机械添加区块、时间戳和规范换行 |
| `capture revise` | 目标必须是既有轻量记录（闪念/有意思/待办）；只能追加用户亲自提供并确认的内容；追加内容必须有实际含义 |
| `capture update` | 目标必须是既有轻量记录；只能整体更新为用户亲自提供并确认的内容；替换"原始记录"节并保留其余节 |
| `capture retitle` | 目标必须是既有轻量记录；只能改为用户亲自确认的新标题；新标题必须非空且有实际含义；标题变化时同步重命名文件（冲突时递增序号）、更新正文首行标题、重写全库引用该卡片的 wikilink（来源快照区除外）并更新状态账本中的路径 |
| `capture transition` | 目标必须是既有轻量记录；目标状态必须属于该类型允许集合；闪念的 `已处理` 由系统保留，不开放手动流转 |
| `connect propose` | 两端都必须是已存在的正式卡片；它只增加形成关系之外的可选语义连接，不承担普通永久卡片的准入激活 |
| `connect accept` | 必须是用户确认的既有 `pending` 连接候选，接受时原子写入双向关系 |
| `connect withdraw` | 只撤回仍为 `pending` 的连接候选；必须带明确撤回原因；撤回后候选不可接纳 |
| `connect disconnect` | 目标必须是账本中已接受的连接；必须带明确断开原因；原子移除两端卡片的连接条目并更新账本 |
| `review` | 只读返回待处理材料，并按创建时间标记超过 48 小时的陈旧闪念 |
| `maintain metadata` | 只机械删除正式内容中已废弃的 `summary` 字段，不改正文、快照或关系 |
| `maintain source-tags` | 只设置或清除来源 Frontmatter 的可选 `tags` 字段（用户命名的高辨识度实体名，全中文、去重、≤2 条）；空列表即清除；重跑传新值即整体替换；不触碰快照区、不触发哈希变化 |

人的发起、作者权、苏格拉底式澄清与完整草稿确认规则由 `AGENTS.md` 和相关 Skills 定义；本文件只校验其在 CLI 边界留下的确认参数、候选状态和内容哈希。普通永久卡片必须先以形成来源连接完成最小网络激活；在此之外没有合适对象时，允许零条额外语义连接。母题、行动和索引卡片暂不受这项普通永久卡片门禁约束。

## 事务、索引与日志

`.goodidea/state.json` 保存事务幂等账本、来源映射、提案与连接。网页来源映射键是 `canonical_url`，本地来源映射键是 `local:sha256:<origin_sha256>`；两者都不包含原始分享参数或本机绝对路径。每次事务先在 `.goodidea/transactions/` 建立可恢复备份，再原子替换目标文件，最后只暂存并提交该事务相关路径。

Obsidian 与 CLI 生成的 Wiki 链接统一使用从仓库根目录开始的路径。`.obsidian/` 中稳定的阅读设置和样式纳入 Git；`workspace.json` 等本机布局不提交。

`index.md` 每次成功事务重新生成，只展示卡片标题链接和中文状态。正式内容没有 `summary` 字段。`log.md` 中的 `<summary>` 是一次事务的人类可读操作说明，同时保存在状态账本和 Git 提交信息中，不是任何卡片的内容摘要。每条日志格式为：

```text
[YYYY-MM-DD HH:MM:SS +0800] <action> | <summary> | tx=<transaction-id>
```

## 信任模型

网页和外部本地文档的正文、标题、作者、图片替代文本与元数据均为不可信输入，只能作为数据保存。CLI 不解析或执行其中的提示词、Shell、HTML 脚本、链接跳转建议或工具调用。
