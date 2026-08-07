# Good idea v0.1 Schema

## 目录与类型

| 目录 | `type` | 允许状态 |
|---|---|---|
| `闪念空间/` | `flash` | `pending`, `processed`, `expired`, `dismissed` |
| `溯源空间/` | `source` | `complete`, `partial`, `failed`, `update_available` |
| `有意思空间/` | `interesting` | `pending`, `processed`, `dismissed` |
| `待办空间/` | `todo` | `open`, `done`, `cancelled` |
| `永久空间/永久卡片/` | `permanent` | `active`, `revised`, `retired` |
| `永久空间/母题卡片/` | `mother` | `open`, `evolving`, `retired` |
| `永久空间/行动卡片/` | `action` | `planned`, `acting`, `observing`, `reviewed` |
| `永久空间/索引卡片/` | `index` | `active`, `revised`, `retired` |

所有正式笔记必须包含 JSON-compatible YAML Frontmatter：`id`、`type`、`title`、`status`、`created_at`、`updated_at`。链接资料还包含 `canonical_url`、`fetched_at`、`snapshot_sha256` 与 `capture_status`。用户提交的原始分享链接只用于当次抓取，不持久化。

## 稳定 ID

- 闪念：`FLA-YYYYMMDD-xxxxxxxx`
- 来源：`SRC-xxxxxxxxxxxx`，由规范化 URL 决定，同一来源稳定复用。
- 有意思：`INT-YYYYMMDD-xxxxxxxx`
- 待办：`TODO-YYYYMMDD-xxxxxxxx`
- 永久/母题/行动/索引：`PER|MOT|ACT|IDX-YYYYMMDD-xxxxxxxx`
- 提案：`PRP-xxxxxxxxxxxx`

调用方可以提供 `--transaction-id`。同一事务 ID 重放必须返回原结果且不再创建文件或 Git 提交。

ID 是系统内部的稳定身份，用于去重、状态关联、来源关系、事务审计和标题变更后的对象识别。ID 不属于标题，也不得出现在内容文件名或生成式索引中。

## 人类可读文件名

五个空间中的所有内容文件统一使用 `YYYY-MM-DD-标题.md`，日期取 `created_at` 的本地创建日期。文件名冲突时在标题后机械追加 `-2`、`-3`；不得用 ID 解决冲突。标题和文件名可以面向人调整，内部 ID 保持不变。

现有文件通过 `goodidea maintain filenames` 原子重命名。该事务同时维护路径链接、来源账本、索引、日志和 Git 历史。

## 内部参数

Markdown Frontmatter 是 CLI 的机器控制面，不是阅读正文。Obsidian 默认隐藏它，用户正常阅读时无需理解或编辑。

| 参数 | 中文含义 | 系统用途 |
|---|---|---|
| `id` / `type` | 稳定身份 / 对象类型 | 在改名后仍识别同一对象，并校验所在空间 |
| `title` / `summary` | 标题 / 索引摘要 | 生成文件名、标题和索引说明 |
| `status` | 生命周期状态 | 区分待处理、已失效、完整、待行动等状态 |
| `created_at` / `updated_at` | 创建 / 更新时间 | 文件命名、排序和演化审计 |
| `source_ids` / `flash_ids` / `derived_from` | 来源 / 闪念 / 生成关系 | 用 ID 维持跨文件关系，不依赖文件名 |
| `canonical_url` | 规范链接 | 点击来源、识别同一来源并去重；原始分享链接不持久化 |
| `capture_status` / `fetched_at` | 抓取结果 / 抓取时间 | 判断快照是否完整及何时取得 |
| `content_sha256` / `snapshot_sha256` | 内容 / 快照哈希 | 检测网页变化并阻止原文快照被静默篡改 |
| `image_failures` | 图片保存失败记录 | 明确标记不完整来源，避免静默依赖远程图片 |

这些参数只能由 CLI 维护。需要排查问题时再查看 `schema.md` 和 `.goodidea/state.json`，不要把它们当成卡片正文。

## Obsidian 产品基线

`.obsidian/app.json`、`appearance.json`、`core-plugins.json` 和 `snippets/goodidea.css` 属于 v0.1 产品基线：默认隐藏 Frontmatter 属性、隐藏内部目录、自动维护链接，并把附件保存到 `.goodidea/assets/`。`workspace.json` 只记录本机临时窗口状态，不进入 Git。

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

## 文献笔记
<!-- goodidea:literature:start -->
待处理
<!-- goodidea:literature:end -->

## 关联闪念
```

标题直接使用文章名称。原文快照紧随标题；用户的文献笔记和关联闪念位于原文之后。来源只永久保存规范链接，不保留带分享或追踪参数的原始链接。

哈希基于两个快照标记之间规范化后的完整文本。Frontmatter 和起始标记中的哈希必须相同。任何写操作开始前都要校验所有来源快照；发现异常则停止。

图片存入 `.goodidea/assets/<内容哈希>.<扩展名>`，正文使用本地相对链接。下载失败时以明确的失败占位文本替换远程图片，来源状态降为 `partial`，不让可读性静默依赖远程图片。

## 状态门禁

- 链接预读不持久化。`source commit` 必须带有内容明确的 `--motivation`。
- 永久卡片由用户主动发起。Agent 以一次一个问题的苏格拉底式交流帮助用户澄清观点。经用户授权后，可以删除口语停顿与重复、调整顺序、提炼标题并结构化为 Markdown，但不得增加新观点。
- Agent 必须展示完整结构化草稿；只有用户明确确认全文后，才可调用 `permanent propose --confirm-user-approved-structure`，记录为 `user_confirmed_agent_structured`。
- 用户确认最终草稿并明确要求正式创建后，`permanent accept --confirm-user-approved` 才能发布。旧的用户逐字草稿与 Agent 仅提炼标题模式继续兼容。
- 草稿正文不得出现内部负载或“机器数据”区块；ID、状态、来源 ID、内容哈希等内部字段仅放 Frontmatter 和 `.goodidea/state.json`。
- 四种永久卡片遵守同一作者边界。撤销的错误草稿状态为 `withdrawn`，不可接纳，原错误仅由 Git 历史保留。
- `permanent revise` 与 `permanent feedback` 也必须带 `--confirm-user-authored`，只能追加用户亲自写下的修订、现实结果与修正；CLI 可机械添加区块、列表标记和时间戳，并规范化边界换行，但不改变用户措辞。Agent 不维护正文。
- 连接先写 `.goodidea/proposals/connections/`；`connect accept` 只接受既有正式卡片。
- 来源刷新先生成候选并标记 `update_available`；确认后才替换同一文件的快照。
- 闪念创建 48 小时后仍为 `pending`，由 `review --expire` 改为 `expired`。

## 事务、索引与日志

`.goodidea/state.json` 保存事务幂等账本、来源映射、提案与连接。每次事务先在 `.goodidea/transactions/` 建立可恢复备份，再原子替换目标文件，最后只暂存并提交该事务相关路径。

Obsidian 与 CLI 生成的 Wiki 链接统一使用从仓库根目录开始的路径。`.obsidian/` 中稳定的阅读设置和样式纳入 Git；`workspace.json` 等本机布局不提交。

`index.md` 每次成功事务重新生成；`log.md` 每条记录格式为：

```text
## [YYYY-MM-DD HH:MM:SS +0800] <action> | <summary> | tx=<transaction-id>
```

## 信任模型

抓取正文、标题、作者、图片替代文本和页面元数据均为不可信输入，只能作为数据保存。CLI 不解析或执行其中的提示词、Shell、HTML 脚本、链接跳转建议或工具调用。
