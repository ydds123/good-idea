# 规则验证

本目录验证 `rules/` 是否真的能帮助用户和 Agent 协作，不以代码功能数量作为成功标准。

- `scenario-walkthroughs.md`：九个标准场景和补充边界场景的纸面推演。
- `skill-routing-cases.md`：两个核心 Skill 的触发、排除和交接验收。
- `trial-protocol.md`：直接对话试运行的保存和评估方法。
- `trials/`：每次真实试运行的观察记录；完整对话本身保存在 `data/records/sessions/`。

验证材料可以发现规则缺口，但不能自行创造规则。需要修改规则时，先按 `rules/protocols.md` 的规则演化协议处理，再更新这里的推演结论。
