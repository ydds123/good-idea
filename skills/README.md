# Skill 层

当前没有正式 Skill。Agent 可以直接读取规则层并调用 Kernel。

只有真实使用证明存在稳定触发方式或明显的上下文负担时，才创建 Skill。

每个 Skill 默认只允许两个文件：

```text
<skill-name>/
├── SKILL.md
└── agents/
    └── openai.yaml
```

- `SKILL.md`：只负责触发识别、需要加载哪些规则和调用顺序。
- `agents/openai.yaml`：只负责界面名称、简介和默认提示。

对象语义、状态、权责、协议、默认值和决策记录必须留在 `rules/`，不得复制进 Skill。
