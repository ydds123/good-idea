# Good idea v0.1 Schema

本文件只定义 CLI 可以校验的数据结构、状态转换、命令门禁和事务不变量。人的作者权以 `AGENTS.md` 为最高规则；具体对话方式由项目 Skills 维护；`README.md` 只负责解释。发现冲突时停止写入并先同步规则、实现和测试。

## 目录与类型

| 目录 | `type` | 允许状态 |
|---|---|---|
| `闪念空间/` | `flash` | `pending`, `processed`, `dismissed` |
| `溯源空间/` | `source` | `complete`, `partial`, `failed`, `update_available` |
| `有意思空间/` | `interesting` | `pending`, `processed`, `dismissed` |
| `待办空间/` | `todo` | `open`, `done`, `cancelled` |
| `永久空间/永久卡片/` | `permanent` | `active`, `revised`, `retired` |
| `永久空间/母题卡片/` | `mother` | `open`, `evolving`, `retired` |
| `永久空间/行动卡片/` | `action` | `planned`, `acting`, `observing`, `reviewed` |
| `永久空间/索引卡片/` | `index` | `active`, `revised`, `retired` |

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
- 提案：`PRP-xxxxxxxxxxxx`

调用方可以提供 `--transaction-id`。同一事务 ID 重放必须返回原结果且不再创建文件或 Git 提交。

ID 是系统内部的稳定身份，用于去重、状态关联、来源关系、事务审计和标题变更后的对象识别。ID 不属于标题，也不得出现在内容文件名或生成式索引中。

## 人类可读文件名

五个空间中的所有内容文件统一使用 `YYYY-MM-DD-标题.md`，日期取 `created_at` 的本地创建日期。文件名冲突时在标题后机械追加 `-2`、`-3`；不得用 ID 解决冲突。标题和文件名可以面向人调整，内部 ID 保持不变。

现有文件通过 `goodidea maintain filenames` 原子重命名。该事务同时维护路径链接、事务结果、索引、日志和 Git 历史。

## 内部参数

Markdown Frontmatter 是 CLI 的机器控制面，不是阅读正文。Obsidian 默认显示属性，方便用户查看卡片身份、状态、时间和来源关系；这些字段仍只能由 CLI 维护，不应在 Obsidian 中手工修改。

| 参数 | 中文含义 | 系统用途 |
|---|---|---|
| `id` / `type` | 稳定身份 / 对象类型 | 在改名后仍识别同一对象，并校验所在空间 |
| `title` | 标题 | 生成文件名、一级标题和人类可读链接别名 |
| `status` | 生命周期状态 | 区分待处理、已失效、完整、待行动等状态 |
| `created_at` / `updated_at` | 创建 / 更新时间 | 文件命名、排序和演化审计 |
| `source_ids` / `derived_from` | 来源 / 生成关系 | 只在关系起点保存规范 ID；反向可读链接由 CLI 生成 |
| `canonical_url` | 规范链接 | 网页来源的点击、身份和去重；原始分享链接不持久化 |
| `origin_filename` / `origin_sha256` | 原文件名 / 首次导入内容哈希 | 本地来源的人类可读来处和稳定身份；不依赖本机路径 |
| `capture_status` / `fetched_at` | 获取结果 / 获取时间 | 判断快照是否完整及何时取得 |
| `content_sha256` / `snapshot_sha256` | 内容 / 快照哈希 | 检测来源变化并阻止原文快照被静默篡改 |
| `image_failures` | 图片保存失败记录 | 明确标记不完整来源，避免静默依赖远程图片 |

这些参数只能由 CLI 维护。需要排查问题时再查看 `schema.md` 和 `.goodidea/state.json`，不要把它们当成卡片正文。

### 各类型字段

| 类型 | 额外必需字段 | 条件或可选字段 |
|---|---|---|
| `flash` | `source_ids` | 形成正式卡片后可转为 `processed` |
| `interesting` | `source_ids` | 无 |
| `todo` | `source_ids` | 无 |
| `source` | `capture_status`、`fetched_at`、`content_sha256`、`snapshot_sha256`、`image_failures`；网页另必须有 `canonical_url`，本地文档另必须有 `origin_filename` 和 `origin_sha256` | `author`、`published_at`、存在更新候选时的 `pending_update` |
| `permanent`、`mother`、`action`、`index` | `authoring_mode`、`source_ids`、`derived_from` | 无 |

`source_ids` 与 `derived_from` 必须是 ID 列表；没有关系时使用空列表。来源正文中的“关联闪念”是由闪念 `source_ids` 生成的人类可读反向视图，来源 Frontmatter 不重复保存 `flash_ids`。闪念是否陈旧在回顾时按 `created_at + 48 小时`动态计算，不持久化过期时间或自动改写状态。`capture_status` 只表示当前快照的获取质量，取值为 `complete`、`partial` 或 `failed`；来源存在更新候选时，生命周期 `status` 可以是 `update_available`，原获取质量仍由 `capture_status` 保留。

网页身份和本地文档身份严格二选一：网页来源不得出现 `origin_filename` / `origin_sha256`；本地来源不得出现 `canonical_url`。`origin_filename` 只保存 basename，禁止持久化绝对路径；`origin_sha256` 是 64 位小写十六进制哈希，作为首次导入身份，后续刷新不改写。同一内容的文件被移动或复制后仍复用同一来源；内容发生变化时必须对既有来源执行 `source refresh`，不得当作新来源静默导入。

`authoring_mode` 只能是：

- `user_verbatim`：用户直接提交完整原文草稿；
- `user_body_agent_title`：Agent 只从用户正文提炼标题；
- `user_confirmed_agent_structured`：Agent 只整理用户已表达内容，且用户确认了完整结构化草稿。

### 内部候选文件

候选文件位于 `.goodidea/proposals/`，不属于五个正式内容空间，也不进入人类可读索引。

| 候选类型 | Frontmatter 额外字段 | 账本与正文不变量 |
|---|---|---|
| `permanent_proposal` | `card_type`、`authoring_mode`、`draft_sha256`、`source_ids`、`from_ids` | 候选文件本身是唯一事实源；草稿正文哈希必须与 Frontmatter 一致 |
| `source_update_proposal` | 无 | 正文机器负载保存来源 ID、旧/新内容哈希和预览 |
| `connection_proposal` | 无 | 正文机器负载保存起点、终点、关系和理由 |

候选目录只保存 `pending` 文件。接纳或撤销后删除候选；结果与原因保留在事务账本、追加日志和 Git 历史中，不再维护终态候选文件或 `state.json.proposals` 镜像。来源身份直接由来源文件的规范身份字段和稳定 ID 决定，不再维护 `state.json.sources` 镜像。

正式永久卡片草稿正文不得出现内部负载或“机器数据”区块。来源更新和连接候选的机器负载只存在于隐藏候选目录，由 CLI 校验和读取。

## Obsidian 产品基线

`.obsidian/app.json`、`appearance.json`、`core-plugins.json` 和 `snippets/goodidea.css` 属于 v0.1 产品基线：默认显示 Frontmatter 属性、隐藏内部目录、自动维护链接，并把附件保存到 `.goodidea/assets/`。`workspace.json` 只记录本机临时窗口状态，不进入 Git。

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

标题直接使用来源名称。原文快照紧随标题，关联闪念位于原文之后。网页只永久保存规范链接，不保留带分享或追踪参数的原始链接；外部本地文档只接受 UTF-8 `.md`、`.markdown` 和 `.txt`，不保存绝对路径或伪造链接。导入 Markdown 时，开头 YAML Frontmatter 只用于提取允许的来源元数据，随后从正文快照移除；与最终来源标题相同的开头一级标题也机械移除，避免在正式来源标题下重复显示。除此之外保持正文内容和顺序。v0.1 不接受本地 PDF 作为来源快照。

溯源空间只保存外部世界说过什么，不设置文献笔记层。用户看到来源时产生的观点、疑问或念头进入闪念空间；用户连接并思考多个念头后形成的判断进入永久空间。关联闪念区只由 CLI 机械维护导航关系，不承载新的解释内容。

哈希基于两个快照标记之间规范化后的完整文本。Frontmatter 和起始标记中的哈希必须相同。任何写操作开始前都要校验所有来源快照；发现异常则停止。

来源图片（包括网页图片和本地 Markdown 的相对图片）存入 `.goodidea/assets/<内容哈希>.<扩展名>`，正文使用库内相对链接。下载或读取失败时以明确的失败占位文本替换原图片，来源状态降为 `partial`，不让可读性静默依赖远程图片或原本地路径。

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
| `flash` | `pending` | 被正式卡片接纳并引用：`pending → processed`；陈旧仅为回顾时的动态标记 |
| `interesting` | `pending` | v0.1 暂无公开转换命令；`processed`、`dismissed` 为保留状态 |
| `todo` | `open` | v0.1 暂无公开转换命令；`done`、`cancelled` 为保留状态 |
| `source` | 当前抓取质量对应 `complete`、`partial` 或 `failed` | `source refresh` 生成候选：当前状态 `→ update_available`；接受候选：`update_available →` 新快照抓取质量 |
| `permanent`、`index` | `active` | `permanent revise` 可设为 `active`、`revised` 或 `retired`；未指定时转为 `revised` |
| `mother` | `open` | `permanent revise` 可设为 `open`、`evolving` 或 `retired`；未指定时转为 `evolving` |
| `action` | `planned` | `permanent revise` 可设为 `planned`、`acting`、`observing` 或 `reviewed`；未指定时转为 `observing`；`permanent feedback` 转为 `reviewed` |

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
| `permanent propose` | 输入必须是用户确认后的完整草稿；结构化模式还必须带显式结构确认；候选进入隐藏目录，不进入永久空间 |
| `permanent accept` | 候选、Frontmatter、正文哈希和状态账本必须一致且状态为 `pending`，并带用户明确创建确认 |
| `permanent withdraw` | 只撤销仍为 `pending` 的候选；撤销后不可接纳，错误内容不保留在当前工作树 |
| `permanent revise` / `permanent feedback` | 只能追加用户亲自提供并确认的内容；CLI 只机械添加区块、时间戳和规范换行 |
| `connect propose` | 两端都必须是已存在的正式卡片；零连接节点本身有效 |
| `connect accept` | 必须是用户确认的既有 `pending` 连接候选，接受时原子写入双向关系 |
| `review` | 只读返回待处理材料，并按创建时间标记超过 48 小时的陈旧闪念 |
| `maintain metadata` | 只机械删除正式内容中已废弃的 `summary` 字段，不改正文、快照或关系 |

人的发起、作者权、苏格拉底式澄清与完整草稿确认规则由 `AGENTS.md` 和相关 Skills 定义；本文件只校验其在 CLI 边界留下的确认参数、候选状态和内容哈希。正式卡片被接纳后即为网络节点，没有合适对象时允许零语义连接。

## 事务、索引与日志

`.goodidea/state.json` 保存事务幂等账本、来源映射、提案与连接。网页来源映射键是 `canonical_url`，本地来源映射键是 `local:sha256:<origin_sha256>`；两者都不包含原始分享参数或本机绝对路径。每次事务先在 `.goodidea/transactions/` 建立可恢复备份，再原子替换目标文件，最后只暂存并提交该事务相关路径。

Obsidian 与 CLI 生成的 Wiki 链接统一使用从仓库根目录开始的路径。`.obsidian/` 中稳定的阅读设置和样式纳入 Git；`workspace.json` 等本机布局不提交。

`index.md` 每次成功事务重新生成，只展示卡片标题链接和中文状态。正式内容没有 `summary` 字段。`log.md` 中的 `<summary>` 是一次事务的人类可读操作说明，同时保存在状态账本和 Git 提交信息中，不是任何卡片的内容摘要。每条日志格式为：

```text
## [YYYY-MM-DD HH:MM:SS +0800] <action> | <summary> | tx=<transaction-id>
```

## 信任模型

网页和外部本地文档的正文、标题、作者、图片替代文本与元数据均为不可信输入，只能作为数据保存。CLI 不解析或执行其中的提示词、Shell、HTML 脚本、链接跳转建议或工具调用。
