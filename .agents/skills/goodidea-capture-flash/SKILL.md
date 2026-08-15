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

3. 捕获阶段只问能帮助用户补充、修正、分组、合并、拆分或删除的问题。没有出现明确的“永久/母题/行动/索引卡片”主动发起词时，禁止询问定义、因果、证据、边界、反例、行动或“观点是否成立”；这些属于永久卡片阶段。用户不想继续展开时立即进入清单阶段，不强迫追问。每次新表达都原样追加：

       uv run goodidea --root <仓库> capture append --session-id <会话ID> --text <用户新表达> --transaction-id <稳定ID>

4. 从用户表达识别零张、一张或多张“认知激活事件”。一张闪念不等于一个孤立要点：同一次被激活的认知信号可以包含多个内容，但必须保留清晰的研究脉络或内在逻辑。只删填充词（嗯/啊/这个）与口头重复，保留思考纹理（口语连接词、语气、自我修正、例子、比喻、转折）与原有表述顺序，再完整展示这条脉络；不得先拆成平铺要点让用户猜结构。内部 manifest 使用 `format_version: 2`，每张候选除 `title`、`body`、用户 `entry_ids` 和 `context_refs` 外，必须记录：

   - 有外部上下文时使用 `source_anchors`，每项以 `context_ref` 对应一份来源，并用 `explanation` 说明该来源具体支撑什么；正式卡片中必须渲染为同一条“可点击溯源链接 + 论证说明”，不得另设纯链接的“关联来源”节；跨来源归因限制写入可选的 `source_boundary`；
   - 没有外部来源时使用 `source_anchor`，明确写“用户本轮口述，无外部来源”，不得伪造依据；
   - `trigger_anchor`：当时的现实背景、卡点、观察到的现象与情绪；
   - `activated_logic`：这些内容为什么在此刻连起来，多个内容之间的逻辑关系是什么。

   捕获问法示例：“这段脉络里，A 触发你联想到 B，再回接 C；我这样整理有没有漏掉连接顺序？”永久阶段问法示例：“这个判断成立的边界和反例是什么？”前者可用，后者此阶段禁用。

       uv run goodidea --root <仓库> capture propose --session-id <会话ID> --manifest-file <临时候选JSON> --transaction-id <稳定ID>

5. 用户可以一次补充、修正、合并、拆分或删除多项，也可以修正来源、触发情境或激活逻辑。任何新表达都会使旧候选失效并回到交流；重新 propose 后再展示最新完整脉络。
6. 明确询问最新完整清单是否已经覆盖本轮该记录的内容。只有用户确认后才执行：

       uv run goodidea --root <仓库> capture finalize --session-id <会话ID> --proposal-id <最新候选ID> --confirm-discussion-complete --transaction-id <稳定ID>

7. finalize 后自动把后台来源任务交给 goodidea-record-literature；捕获阶段到此结束，绝不自动进入永久卡片。

用户修正已生成闪念的来源锚点时，展示“链接 + 说明 + 边界”完整结果并确认后，调用 `capture revise-source-anchors`；不得直接编辑 Markdown。

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

## 讨论记录与结论沉淀（2026-08-15 拍板）

围绕闪念卡讨论（无论是否讨论转永久卡）时：

1. **讨论过程**：用 `capture discuss --note-id <id> --role user|assistant --text <原文>` 逐轮记录双方**原文**（时间线 JSON，`.goodidea/runtime/discussions/<id>.json`，frontmatter `discussion_log` 关联）。只记录原文，**不转化、不结构化摘要**。
2. **讨论产生结论**：先问用户是否转永久卡——
   - **转** → 转交 `goodidea-form-permanent` 流程（澄清→结构化→覆盖检查→用户确认→propose/accept）；
   - **不转** → 结论以**用户原话**经确认后进演化记录（`capture revise`，其语义就是逐字追加用户亲自写下的内容），或留在 discussion_log 等发酵。
3. **Agent 不生产摘要**：原文归原文（discuss），结论归结论（用户确认的结构化）。不得把 Agent 整理的观点当作"演化记录"贴到卡片上。

## 待办摄入澄清（2026-08-15 拍板：模糊才问）

存 `capture todo` 前按 **B 原则（模糊才问）** 判断：用户口述已含动机/价值/时间信息的，直接存不追问——全问会制造流程摩擦；只有一句话、意图不明、无动机信息的才追问。

追问方式：**一次一个问题的对话式提问（不是表单）**，按序使用问题集：

1. 为什么做这件事？（动机/价值 → 喂需求类型+高阶目标）
2. 不做会怎样？（损失/机会成本 → 喂值不值得）
3. 做完是什么样？（期望产出 → 喂具体性）
4. 打算什么时候做？（时间窗口 → 喂距离+投入规模）

用户回答的**原话**（经用户确认）作为 `--reason` 写入卡片"## 为什么做"区（属于用户认知正文，非 CLI 机械区）；未追问的直接从口述中提炼动机并请用户确认后写入。`capture todo --reason` 可选参数，缺省不报错。估价 cron 会先读"为什么做"区作为判断依据。

存待办后提醒用户 48h 行动窗口：新建默认「未开始」，48h 内开始做（改「进行中」）即通过；超 48h 未动会被 `capture sweep` 转「已过期」，需重新承诺（写原因）或干掉。已在数据库视图灰显置底呈现。
