# 闪念讨论记录与结论沉淀（低频附档）

> 文档性质：从 SKILL.md 外置的低频规则附档（2026-08-23 yao 规范重构，规则语义未变，原文搬迁）。围绕闪念卡讨论时按本规则留档；不讨论时无需读取。

## 讨论记录与结论沉淀（2026-08-15 拍板）

围绕闪念卡讨论（无论是否讨论转永久卡）时：

1. **讨论过程**：用 `capture discuss --note-id <id> --role user|assistant --text <原文>` 逐轮记录双方**原文**（时间线 JSON，`.goodidea/runtime/discussions/<id>.json`，frontmatter `discussion_log` 关联）。只记录原文，**不转化、不结构化摘要**。**同一卡片始终追加同一档案文件**（单文件时间线，不开新文件——讨论从上次停处延续）。
2. **讨论产生结论**：先问用户是否转永久卡——
   - **转** → 转交 `goodidea-form-permanent` 流程（澄清→结构化→覆盖检查→用户确认→propose/accept）；
   - **不转** → 结论以**用户原话**经确认后进演化记录（`capture revise`，其语义就是逐字追加用户亲自写下的内容），或留在 discussion_log 等发酵。
3. **Agent 不生产摘要**：原文归原文（discuss），结论归结论（用户确认的结构化）。不得把 Agent 整理的观点当作"演化记录"贴到卡片上。

## 关联

- `capture discuss` 命令细节见 goodidea-development skill 与 CLI 帮助
- 转永久卡流程见 `.agents/skills/goodidea-form-permanent/SKILL.md`
