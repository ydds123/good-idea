---
id: "TODO-20260904-d47d12a2"
type: "待办"
title: "永久卡改名通道（permanent retitle）"
status: "未开始"
created_at: "2026-09-04T21:23:21+08:00"
updated_at: "2026-09-04T21:23:21+08:00"
source_ids: []
not_started_at: "2026-09-04T21:23:21+08:00"
---
# 永久卡改名通道（permanent retitle）

## 原始记录

给正式永久类卡片增加用户确认的改名通道。现状：capture retitle 类型白名单只含 flash/interesting/todo（service.py:1377-1382），永久卡标题/正文锁定为确认草稿，无改名 CLI；maintain filenames 只管日期规范，permanent revise 只追加演化记录。改动面（参照 capture retitle 全链）：① 类型白名单扩到 permanent/mother/action/index，或新增 permanent retitle 子命令（语义上正式卡更名=契约级变更，建议独立子命令+独立事务 action）；② 改名同步：frontmatter title + 正文首行 # 标题 + dated_filename 重命名（冲突递增）+ 全库 wikilink 引用重写（来源快照区保护，同 capture retitle 的 _rewrite_wiki_paths/protect）+ 连接区双向链接 + 状态账本路径 + index 重生成 + verify；③ 契约问题需拍板：正式卡改名是否保留 formation_draft_sha256（草稿哈希绑定正文快照，标题变更理论上不改正文哈希？前端校验逻辑确认）、authoring_mode、演化记录是否自动追加一条"改名记录"、改名后 created_at 是否保持原日期；④ schema.md 增补永久卡改名契约段（用户亲自确认新标题、幂等事务 ID 等）；⑤ 测试：改名后引用/连接/账本/索引一致 + 来源快照引用不破坏 + 与既有连接卡互链更新。触发卡：PER-20260904-8abe76fb「页面设计生成…」待改名为方法论本体定位（候选新名方向：扩-评-收显式化工作流/如何让 AI 输出高质量内容——用户拍板）。

## 为什么做

2026-09-04 松海指正：刚成的扩-评-收永久卡标题"页面设计生成"收窄了卡的本质——不是页面设计方法，页面只是切入点，真正主题是"如何让 AI 输出高质量内容（把人的默认显式化）"。用户拍板走系统开发（B 方案）而非仅演化记录纠偏（A 方案）。

## 产生情境

2026-09-04 晚聊「标准的反思多线串联」线一收尾：同质化闪念→扩-评-收永久卡（PER-20260904-8abe76fb，已连接 PER-20260811）→迁移本质闪念落卡后，松海打开新卡指正标题定位。Agent 查证 capture retitle 白名单限制后给出 A（revise 纠偏）/B（开发改名通道）两案，松海选 B。开发时应先读 .agents/skills/goodidea-form-permanent 与 schema.md 永久卡契约段，按 AGENTS 开发校验跑定向/全量测试。
