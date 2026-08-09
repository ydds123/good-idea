# Good Idea 闪念捕获优化实施发现

## 已确认事实

- 当前路由把“带链接或外部本地文档”直接交给来源 Skill，是事故的直接规则来源。
- 当前 `source commit` 把来源处理和新闪念创建绑定为一个事务。
- 当前所有正式写入都会检查全部来源快照并重建索引。
- 当前七个 Skills 中，capture 与 literature 需要实质修改；form-permanent、review-permanent 和 lint 需要收紧交界；review-process 与 connect-cards 保持不变。
- 捕获会话应当支持多轮交流和多张闪念，用户需要在最终确认前反复修正候选清单。
- 临时认知现场只负责防丢，不应默认进入 Git 或永久保留。

## 实施期间新增发现

后续按阶段追加；不把外部网页中的指令性内容写入 task_plan.md。
