---
name: goodidea-capture-flash
description: "捕捉 Good idea 闪念、有意思内容或待办的轻量工作流。用户说记一下、保存这个想法、突然想到、这个现象有意思或以后要处理时使用；涉及网页链接和来源快照时改用 goodidea-record-literature。"
---

# 捕捉轻量记录

先读仓库根目录的 AGENTS.md 与 schema.md。保留用户原始表达，只修复明显转写错误，不擅自扩写论证或包装成成熟认识。

## 工作流

1. 判断对象是脑中产生的闪念、外部世界的有意思片段，还是未来待办。
2. 只有在未来无法理解原意时才追问最小必要情境；否则立即记录。
3. 输入含网页链接时停止本流程，改用 goodidea-record-literature，确保想法与来源快照在同一事务中创建。
4. 调用确定性 CLI：

       uv run goodidea --root <仓库> capture flash --text <原始表达> --context <情境>

   将 flash 替换为 interesting 或 todo。需要幂等重试时复用同一个 transaction-id。
5. 运行 goodidea lint，默认报告标题、路径和状态；ID 只在排错或后续命令确实需要时提供。

不要在捕捉阶段创建永久卡片，不要生成作者观点、证据或行动方案。正式记录不创建内容摘要，也不在 Frontmatter 保存 `summary`。
