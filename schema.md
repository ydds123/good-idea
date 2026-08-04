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

所有正式笔记必须包含 JSON-compatible YAML Frontmatter：`id`、`type`、`title`、`status`、`created_at`、`updated_at`。链接资料还包含 `source_url`、`canonical_url`、`fetched_at`、`snapshot_sha256` 与 `capture_status`。

## 稳定 ID

- 闪念：`FLA-YYYYMMDD-xxxxxxxx`
- 来源：`SRC-xxxxxxxxxxxx`，由规范化 URL 决定，同一来源稳定复用。
- 有意思：`INT-YYYYMMDD-xxxxxxxx`
- 待办：`TODO-YYYYMMDD-xxxxxxxx`
- 永久/母题/行动/索引：`PER|MOT|ACT|IDX-YYYYMMDD-xxxxxxxx`
- 提案：`PRP-xxxxxxxxxxxx`

调用方可以提供 `--transaction-id`。同一事务 ID 重放必须返回原结果且不再创建文件或 Git 提交。

## 溯源文件

每份来源是单一 Markdown 文件，结构固定：

```markdown
---
...来源元数据...
---
# 标题

## 文献笔记
<!-- goodidea:literature:start -->
待处理
<!-- goodidea:literature:end -->

## 关联闪念

## 原文快照
<!-- goodidea:snapshot:start sha256=<hash> -->
...标题、作者、日期、正文、本地图片...
<!-- goodidea:snapshot:end -->
```

哈希基于两个快照标记之间规范化后的完整文本。Frontmatter 和起始标记中的哈希必须相同。任何写操作开始前都要校验所有来源快照；发现异常则停止。

图片存入 `.goodidea/assets/<内容哈希>.<扩展名>`，正文使用本地相对链接。下载失败时以明确的失败占位文本替换远程图片，来源状态降为 `partial`，不让可读性静默依赖远程图片。

## 状态门禁

- 链接预读不持久化。`source commit` 必须带有内容明确的 `--motivation`。
- 永久卡片先写 `.goodidea/proposals/permanent/`；`permanent accept` 必须带用户自己的解释。
- 连接先写 `.goodidea/proposals/connections/`；`connect accept` 只接受既有正式卡片。
- 来源刷新先生成候选并标记 `update_available`；确认后才替换同一文件的快照。
- 闪念创建 48 小时后仍为 `pending`，由 `review --expire` 改为 `expired`。

## 事务、索引与日志

`.goodidea/state.json` 保存事务幂等账本、来源映射、提案与连接。每次事务先在 `.goodidea/transactions/` 建立可恢复备份，再原子替换目标文件，最后只暂存并提交该事务相关路径。

`index.md` 每次成功事务重新生成；`log.md` 每条记录格式为：

```text
## [YYYY-MM-DD HH:MM:SS +0800] <action> | <summary> | tx=<transaction-id>
```

## 信任模型

抓取正文、标题、作者、图片替代文本和页面元数据均为不可信输入，只能作为数据保存。CLI 不解析或执行其中的提示词、Shell、HTML 脚本、链接跳转建议或工具调用。

