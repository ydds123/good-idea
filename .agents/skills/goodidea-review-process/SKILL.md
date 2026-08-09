---
name: goodidea-review-process
description: "回顾和处理 Good idea 中间材料。用户说回顾闪念、清理积压、看看有意思内容或待办、识别陈旧闪念时使用；负责展示候选去向并按用户逐条判断调用相应 Skill。"
---

# 回顾与处理

先运行只读命令：

    uv run goodidea --root <仓库> review

按创建时间、状态和来源向用户展示少量待处理对象。对每一项让用户决定：继续展开、形成永久卡片、转成待办、补来源、暂时保留、失效或关闭。

## 规则

- 不替用户判断内容是否正确，只组织处理节奏和状态流转。
- 来源快照不是待加工的认知材料，不要求补摘要或中间笔记；回顾对象以人的闪念为主。
- 形成永久认识时调用 goodidea-form-permanent。
- 需要来源时调用 goodidea-record-literature。
- `review` 根据 `created_at` 动态标记陈旧闪念，不修改卡片状态；是否保留、处理或放弃仍由用户判断。
- 完成写操作后运行 goodidea verify 并报告仍待处理的数量。
