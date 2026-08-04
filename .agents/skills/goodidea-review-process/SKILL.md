---
name: goodidea-review-process
description: "回顾和处理 Good idea 中间材料。用户说回顾闪念、清理积压、处理文献笔记、看看待办或让过期闪念失效时使用；负责展示候选去向并按用户逐条判断调用相应 Skill。"
---

# 回顾与处理

先运行只读命令：

    uv run goodidea --root <仓库> review

按创建时间、状态和来源向用户展示少量待处理对象。对每一项让用户决定：继续展开、形成永久卡片、转成待办、补来源、暂时保留、失效或关闭。

## 规则

- 不替用户判断内容是否正确，只组织处理节奏和状态流转。
- 形成永久认识时调用 goodidea-form-permanent。
- 需要来源时调用 goodidea-record-literature。
- 只在执行维护或用户要求时运行 review --expire；该命令会把超过 48 小时仍 pending 的闪念改为 expired。
- 完成写操作后运行 goodidea verify 并报告仍待处理的数量。

