---
name: goodidea-capture-flash
description: "捕捉 Good idea 闪念及多轮认知会话。用户正在表达、补充、修正或审阅本轮想法时使用；即使附带网页、Markdown 或 TXT，也由本 Skill 保持前台，文件和链接只作为上下文。只有用户明确切换到永久卡片阶段才交接后续 Skill。"
---

# 捕捉闪念与认知现场

先读仓库根目录的 AGENTS.md 与 schema.md。保留用户原始表达，只修复明显转写错误，不擅自扩写论证或包装成成熟认识。

## 阶段优先级

当前存在 active、reviewing 或 paused 捕获会话时，本 Skill 优先于关键词和附件类型。用户说“以后可以形成永久卡片”不代表已经切换阶段；只有用户明确结束当前捕获并主动发起永久卡片，才交给后续 Skill。

## 多轮捕获工作流

1. 识别强闪念信号后立即用运行时命令保护用户第一段表达；它不进入 Git、索引或正式日志：

       uv run goodidea --root <仓库> capture start --text <用户原话> --context-ref <链接或文件> --transaction-id <稳定ID>

2. 文件和链接只做可访问性检查并按需读取。将结果与轻量指纹写回运行时会话；不运行来源 preview、图片处理或全库验证：

       uv run goodidea --root <仓库> capture context-check --session-id <会话ID> --ref <上下文> --status <readable|unreadable|partial> --fingerprint-file <临时JSON> --transaction-id <稳定ID>

3. 围绕用户想法一次只问一个有推进价值的问题。用户不想继续展开时立即进入清单阶段，不强迫追问。每次新表达都原样追加：

       uv run goodidea --root <仓库> capture append --session-id <会话ID> --text <用户新表达> --transaction-id <稳定ID>

4. 从用户表达识别零张、一张或多张闪念。默认向用户展示标题和一至两句中心意思；内部 manifest 为每张候选记录用户 entry_ids 和相关 context_refs：

       uv run goodidea --root <仓库> capture propose --session-id <会话ID> --manifest-file <临时候选JSON> --transaction-id <稳定ID>

5. 用户可以一次补充、修正、合并、拆分或删除多项。任何新表达都会使旧候选失效并回到交流；重新 propose 后再展示最新清单。
6. 明确询问最新完整清单是否已经覆盖本轮该记录的内容。只有用户确认后才执行：

       uv run goodidea --root <仓库> capture finalize --session-id <会话ID> --proposal-id <最新候选ID> --confirm-discussion-complete --transaction-id <稳定ID>

7. finalize 后自动把后台来源任务交给 goodidea-record-literature；捕获阶段到此结束，绝不自动进入永久卡片。

## 暂停、恢复和放弃

       uv run goodidea --root <仓库> capture pause --session-id <会话ID> --transaction-id <稳定ID>
       uv run goodidea --root <仓库> capture resume --session-id <会话ID> --transaction-id <稳定ID>
       uv run goodidea --root <仓库> capture status --session-id <会话ID>
       uv run goodidea --root <仓库> capture discard --session-id <会话ID> --confirm-user-abandoned --transaction-id <稳定ID>

放弃必须来自用户明确指令，产生零正式写入。任务异常不等于放弃；下次恢复即可。

## 单次轻量记录

用户明确说“只记录，不讨论”，或对象是有意思内容/待办时，可以继续使用：

       uv run goodidea --root <仓库> capture flash --text <原始表达> --context <情境>

   将 flash 替换为 interesting 或 todo。需要幂等重试时复用同一个 transaction-id。
正式单次记录完成后运行 goodidea lint；多轮捕获前台不运行，finalize 和后台维护完成后再统一 verify。

不要在捕捉阶段创建永久卡片，不要生成作者观点、证据或行动方案。候选可以忠实整理用户表达，但不得增加新主张；用户确认承担最终归属门禁。正式记录不创建内容摘要，也不在 Frontmatter 保存 `summary`。
