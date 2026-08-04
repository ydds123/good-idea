---
name: goodidea-connect-cards
description: "为 Good idea 正式卡片提出并确认语义连接。用户询问卡片关系、希望接入卡片盒、建立支持冲突演化或例证关系时使用；先展示连接理由，用户确认后才写入双向链接。"
---

# 连接卡片

读取两张正式卡片及其来源。关系必须表达可解释的语义，例如支持、冲突、限定、例证、演化、行动验证或索引入口，不能只因关键词相同而连接。

## 两阶段流程

1. 说明候选关系、方向和理由。
2. 调用候选命令：

       uv run goodidea --root <仓库> connect propose --from-id <ID> --to-id <ID> --relation <关系> --rationale <理由>

3. 向用户展示候选并等待明确确认。
4. 确认后调用：

       uv run goodidea --root <仓库> connect accept --proposal-id <ID>

5. 运行 goodidea verify，确认双向链接、连接账本和索引一致。

不要自动接受连接，不要创建只停留在关键词层面的表面关系。

