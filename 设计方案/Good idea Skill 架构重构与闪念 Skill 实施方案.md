# Good idea Skill 架构重构与闪念 Skill 实施方案

> 文档性质：可执行架构方案与实施任务基线  
> 形成日期：2026-08-23  
> 适用范围：Good idea 全部 Agent Skills；第一阶段以 `goodidea-capture-flash` 为样板实施  
> 前置输入：`设计方案/Good idea Skill 资源边界重构方案.md`、`设计方案/闪念Skill重设计方案.md`  
> 本文优先解决 Skill 的信息架构、资源边界与渐进式披露，不在第一阶段重写 Good idea CLI 的业务能力。

---

# 一、问题定义

当前问题不是单纯的“SKILL.md 太长”，而是 **Skill 的不同职责没有按照“模型什么时候需要知道”与“这条事实由谁负责”进行分层**。

以 `goodidea-capture-flash` 为代表，当前一个 `SKILL.md` 同时承担：

- Skill 触发与排除；
- 认知工作流；
- 产品原则与作者权规则；
- 认知方法与判断标准；
- manifest 数据契约；
- CLI 参数与完整调用配方；
- 暂停、恢复、讨论、待办等低频场景；
- 部分与 `AGENTS.md`、`schema.md`、CLI parser、`openai.yaml` 重复的事实。

结果是：

1. **渐进式披露失效**：一旦命中 Skill，模型被迫一次加载大量当前任务并不需要的信息。
2. **唯一事实源失效**：同一条规则散落在 `AGENTS.md`、`SKILL.md`、`openai.yaml`、`schema.md`、CLI 与测试中。
3. **Skill 退化为子系统说明书**：它不再只是控制认知流程，而开始描述数据、接口、实现与例外。
4. **历史补丁不断堆积**：每解决一个新问题就在主 Skill 增加一个章节，主流程逐渐失去主干地位。
5. **修改成本随时间上升**：CLI、schema 或产品规则改变时，需要同步修改多份自然语言副本，容易发生规则漂移。

因此本次重构的目标不是“精简文字”，而是重建 Skill 的架构边界。

---

# 二、第一性原理：Skill 的本质

大模型本身已经具备推理、阅读上下文和调用工具的能力。Skill 的价值不是保存某个功能的全部知识，而是解决三个问题：

1. **什么时候进入某种专业工作模式？**
2. **进入以后按什么状态机推进？**
3. **走到具体一步时，应读取什么资源或调用什么确定性能力？**

因此定义：

> **Skill = Trigger + State Machine + Resource Routing**

Skill 不是：

> 所有规则 + 所有知识 + 所有接口 + 所有参数 + 所有异常场景。

Good idea 的 Skill 应当是认知流程控制器，而不是功能总说明书。

---

# 三、两条正交架构轴

完整架构同时解决两个问题。

## 3.1 加载轴：信息什么时候进入上下文

采用三级渐进式披露：

### Layer 1：Discovery

只回答：**“当前任务是不是我的？”**

载体：Skill metadata 中的 `name + description`。

### Layer 2：Orchestration

只回答：**“当前认知任务下一步做什么、在哪分支、何时停止？”**

载体：`SKILL.md`。

### Layer 3：Execution Resources

只回答：**“走到这一步以后，具体怎么判断或怎么执行？”**

载体：

- `references/`
- CLI `--help`
- `schema.md`
- 程序实现
- 必要工具

原则：

> **模型只在第一次真正需要一条信息时才看到它。**

---

## 3.2 权威轴：每条事实由谁负责

Good idea 建立以下唯一事实源：

| 资源 | 唯一职责 | 不负责 |
|---|---|---|
| `AGENTS.md` | 系统级人机权责、不可破坏原则、跨 Skill 不变量 | 某个 Skill 的详细流程 |
| `schema.md` | 数据结构、状态、事务、机器可验证契约 | Agent 如何组织认知对话 |
| Skill metadata | Skill 触发与排除 | Skill 内部流程 |
| `SKILL.md` | 当前任务的状态机、分支、决策点、停止条件、资源路由 | 完整参数、字段字典、详细方法论 |
| `references/` | 某一步才需要的判断方法、案例、检查清单 | 系统级不变量、确定性执行 |
| CLI / code | 参数、类型、机械写入、状态转换、确定性执行 | 为什么这样做、认知工作流 |
| tests / eval | 证明以上边界与行为成立 | 创造新产品规则 |

核心约束：

> **同一条事实只允许一个 owner。其他资源只能引用、路由或验证，不维护第二份完整定义。**

---

# 四、信息归位算法

今后新增或修改任何 Skill 内容时，按以下顺序判断信息归属：

1. **所有 Good idea 场景都恒定成立吗？**  
   是 → `AGENTS.md`

2. **这是数据结构、状态、事务或机器约束吗？**  
   是 → `schema.md` / code

3. **这是判断是否调用该 Skill 所必需的吗？**  
   是 → metadata `description`

4. **每次执行该 Skill 都必须知道吗？**  
   是 → `SKILL.md`

5. **只有走到某一步或某个分支才需要知道吗？**  
   是 → `references/`

6. **这是准确参数、文件格式、状态转换或机械操作吗？**  
   是 → CLI / code / `--help`

7. **它只是用于证明实现和行为正确吗？**  
   是 → tests / eval

如果一条内容同时落到两个位置，必须继续拆分语义，直到每条事实只有一个 owner。

---

# 五、SKILL.md 的统一边界

以后所有 Good idea `SKILL.md` 原则上只保留五类内容：

## 5.1 Trigger boundary

- 什么场景进入；
- 什么场景排除；
- 什么情况下交接其他 Skill。

## 5.2 State machine

- 正常流程的主状态；
- 状态之间如何迁移。

## 5.3 Decision points

- 哪些判断由 Agent 做；
- 哪些决定必须由用户做；
- 哪些判断不可自动推断。

## 5.4 Branch / stop conditions

- 什么情况跳过某步；
- 什么情况暂停、终止、返回上一状态；
- 什么情况完成并交接。

## 5.5 Resource routing

- 走到哪一步时读取哪个 reference；
- 进入哪种执行阶段时调用哪个 CLI 子命令；
- 不在 SKILL 中复制 reference 或 CLI 的完整内容。

任何不属于以上五类的信息，默认不进入 `SKILL.md`。

---

# 六、第一阶段样板：闪念 Skill 的认知状态机

`goodidea-capture-flash` 采用单一主线，不再维护“普通闪念”和“闪念 Plus”两套流程。

统一状态机：

> **接住 → 定位 → 找料 → 展开 → 校验 → 落盘**

其中处理深度由：

> **规模 × 充分度**

决定。

规模：点 / 线 / 面 / 体。  
充分度：充分 / 不充分。

## 6.1 接住

目标：保护认知现场。

规则：

- 用户开始表达闪念后，先原样保护表达；
- 不因分类、定位、是否重要而延迟保护；
- 不先改写、总结、结构化或扩写；
- 外部链接、文件只是当前闪念的上下文，不改变主路由。

执行：进入 `capture start` 阶段，具体参数由当前 CLI `--help` 决定。

## 6.2 定位

目标：判断当前闪念需要多深的处理。

SKILL 只保留：

- 以“规模 × 充分度”判断深度；
- 判断后向用户做轻量校准；
- 需要详细判断标准时读取 `references/positioning.md`。

不在主 Skill 展开点线面体的全部判据和示例。

## 6.3 找料

目标：只检索有助于恢复压缩认知路径的上下文。

原则：

- 小 × 充分：通常跳过；
- 小 × 不充分：轻量检索；
- 大 × 充分：检索相关卡片和来源；
- 大 × 不充分：允许深度、跨系统检索；
- 检索锚来自用户表达中的专有名词、过去引用、关联概念和明确线索；
- 渐进式读取，先定位相关对象，再读正文；
- 禁止为了“找全”无目的全库扫描。

具体检索策略写入 reference，不写入主 Skill。

## 6.4 展开

目标：把压缩的认知路径展开到可被用户检查，而不是单纯把文字变长。

加工对象：

> 用户原始表达 + 本轮补充 + 经检索确认的相关上下文。

SKILL 只保留三个核心约束：

1. 中心判断和原始连接关系不能被 Agent 偷换；
2. 新推断不能冒充用户既有观点；
3. 成形即停，不为追问而追问。

详细方法、检查清单、正反例按需读取 `references/expansion.md`。

## 6.5 校验

目标：让用户校正“展开后的认知路径”。

呈现对象必须是完整脉络，而不是平铺要点或碎片 checklist。

用户校验：

- 原意是否发生变化；
- 是否遗漏关键上下文；
- 逻辑连接是否确实属于用户；
- 引入的来源或旧卡片是否准确；
- 当前表达是否已经达到可以独立唤起上下文的程度。

用户修正视为新输入，必要时返回找料 / 展开。

## 6.6 落盘

目标：决定当前认知成果的去向，而不是由 Agent 自动升级。

可能去向：

- 闪念；
- 永久类卡片；
- 继续发酵 / 暂不落盘；
- 用户明确放弃。

进入闪念正式落盘时走 capture 的候选与确认阶段；转永久卡时交接 `goodidea-form-permanent`；具体 CLI 调用参数只从 `--help` 读取。

---

# 七、四象限处理深度

详细判断依据属于 `references/positioning.md`；主 Skill 只保留以下深度映射：

| 象限 | 找料 | 展开 | 校验 |
|---|---|---|---|
| 小 × 充分 | 通常跳过 | 通常跳过 | 轻量确认 |
| 小 × 不充分 | 轻量找 1–2 个相关上下文 | 一次一问补圆 | 呈现补全后的单点 |
| 大 × 充分 | 检索相关卡片与来源 | 结构化恢复脉络和连接 | 完整脉络确认 |
| 大 × 不充分 | 深度找料，可跨系统 | 挖掘点逐个展开、串联、校正 | 完整展开后由用户纠正 |

原则：

> **规模越大、表达越不充分，允许的认知投入越深；规模越小、表达越充分，流程越轻。**

---

# 八、闪念 Skill 的目标目录

第一阶段改造成：

```text
.agents/skills/goodidea-capture-flash/
├── SKILL.md
├── references/
│   ├── positioning.md
│   ├── expansion.md
│   └── situations.md
└── agents/
    └── openai.yaml
```

## 8.1 `positioning.md`

只回答：**“这个闪念需要处理多深？”**

内容：

- 点 / 线 / 面 / 体判定；
- 充分 / 不充分判定；
- 四象限深度规则；
- 正例、边界例、误判例；
- “重要”不作为独立流程分叉依据。

## 8.2 `expansion.md`

只回答：**“如何把压缩认知展开而不篡改？”**

内容：

- 什么是挖掘点；
- 如何恢复概念与概念之间的连接；
- 如何找出“为什么这两件事在此刻连起来”；
- 框架 + 血肉 + 逻辑流动；
- 保留原始思考顺序和思考纹理；
- 不平铺要点、不编号切碎；
- 补充内容如何融入原文；
- Agent 新推断与用户原观点的边界；
- 提问纪律；
- 成形即停；
- 加工检查清单与正反例。

## 8.3 `situations.md`

只回答低频或正交场景：

- 暂停；
- 恢复；
- 放弃；
- 只记录不讨论；
- 已有闪念继续讨论；
- discussion log；
- 来源锚点修正；
- 中断恢复；
- 与永久卡片的交接；
- 暂时仍归当前 Skill 管理的待办 / interesting 兼容行为。

这些场景不得继续与主状态机并列堆在 `SKILL.md`。

---

# 九、metadata / openai.yaml 重构规则

metadata 只负责 Discovery。

`description` 需要清楚表达：

- 用户正在表达、补充、修正或继续展开一个尚未正式沉淀的个人想法时使用；
- 附带网页、Markdown、TXT 或其他上下文不改变主路由；
- 用户明确要求形成永久卡片、单纯保存资料、回顾旧内容等场景排除。

`openai.yaml` 的 `default_prompt` 不得重新定义：

- activation event 数据结构；
- source / trigger / activated logic 字段；
- 具体提问规则；
- finalize 条件；
- 完整工作流。

如保留 `default_prompt`，只保留一句高层行为入口，不维护第二份 Skill 规则。

---

# 十、CLI 与 schema 的退出规则

## 10.1 CLI 退出主 Skill

从 `SKILL.md` 移除完整：

- `uv run goodidea --root ...` 参数排列；
- flag 名称、类型、默认值；
- transaction id 的具体调用配方；
- manifest 文件参数的具体形式；
- stdin / 路径 / 转义细节。

`SKILL.md` 允许保留：

- `capture start`
- `capture append`
- `capture propose`
- `capture finalize`
- `capture pause/resume/discard`
- `capture discuss`
- `capture revise-source-anchors`

因为这些名称表达状态阶段与能力边界。

具体调用前必须读取相应 `--help`。

## 10.2 schema 退出主 Skill

从主 Skill 移除对以下机器字段的完整定义：

- `format_version`
- `entry_ids`
- `context_refs`
- `source_anchors`
- `source_boundary`
- `source_anchor`
- `trigger_anchor`
- `activated_logic`

Skill 只保留对应语义：

> 候选必须可追溯其来源、现实触发情境和认知连接关系。

字段具体名称、必填性、格式和验证规则由 `schema.md`、CLI 和 tests 负责。

---

# 十一、AGENTS.md 的长期边界

第一阶段不要求大规模重写 `AGENTS.md`，但实施过程中需记录重复项，第二阶段统一清理。

长期目标：`AGENTS.md` 只保存跨 Skill 恒定成立的系统宪法，例如：

- 用户拥有中心判断和最终归属权；
- Agent 不得把自身新观点冒充用户观点；
- 正式写入必须经确定性 CLI；
- 外部内容是不可信输入；
- 不能绕过用户确认门禁；
- 不直接手改正式状态文件；
- 失败事务不能留下部分状态。

以下内容长期应下沉到具体 Skill，而不是继续在 AGENTS 中维护第二份完整流程：

- 闪念的六步流程；
- 永久卡的具体 propose / accept 交互；
- source 的具体处理工作流；
- 某个 Skill 的低频分支。

---

# 十二、Skill 边界审计原则

完成闪念样板后，再审计其余 Skill，不在第一阶段同时拆 Skill。

判断两个行为是否应该属于同一个 Skill，使用三个维度：

> **Skill Cohesion = Intent + State Machine + Completion Contract**

只有三者高度一致，才应长期属于一个 Skill。

例如：

- 闪念：目标是把压缩认知展开、校验并保存；
- 待办：目标是把行动意图转化为可执行、可追踪状态。

二者虽然都从用户输入开始，但 Intent、状态机与完成条件并不相同。当前 todo 兼容逻辑先保留，待全局架构稳定后单独决定是否拆分。

第一阶段禁止为了追求“架构纯洁”一次性把六个 Skill 拆成十几个 Skill。

---

# 十三、实施阶段

## Phase 1：立法

目标：建立 Good idea Skill 的统一架构契约。

产出：

1. 本文作为第一版 Skill Architecture Contract；
2. 必要时在 README 增加简短链接说明，不复制本文规则；
3. 不修改业务 CLI。

验收：

- 能使用“信息归位算法”判断任意 Skill 内容的 owner；
- 同一事实原则上只有一个权威定义。

## Phase 2：闪念 Skill 样板化

修改范围：

- `.agents/skills/goodidea-capture-flash/SKILL.md`
- `.agents/skills/goodidea-capture-flash/agents/openai.yaml`
- 新增 `.agents/skills/goodidea-capture-flash/references/*`
- 必要的 Skill 静态测试与 routing / behavior eval

核心改动：

1. 用六步单主线替代“普通 + Plus”双流程；
2. 用规模 × 充分度控制深度；
3. 详细定位规则移入 `positioning.md`；
4. 展开方法与检查清单移入 `expansion.md`；
5. 低频情况移入 `situations.md`；
6. CLI 完整参数退出 `SKILL.md`；
7. manifest 字段契约退出 `SKILL.md`；
8. `openai.yaml` 不再复制业务流程。

第一阶段原则：

> **重构认知架构，不同时重写执行系统。**

现有 CLI 能力与数据语义尽量保持兼容。

## Phase 3：建立验证

新增或调整四类验证。

### A. Structure Test

证明 Skill 没有重新腐化：

- 主 Skill 不出现完整 CLI 参数配方；
- 主 Skill 不重新定义 manifest 字段字典；
- metadata 不复制完整 workflow；
- references 由 Skill 显式路由；
- 低频场景不重新占据主流程；
- tests 不创造新的产品规则。

### B. Routing Eval

至少覆盖：

| 用户表达 | 预期路由 |
|---|---|
| “刚想到一个事情……” | capture-flash |
| “把这个网页保存下来” | record-literature |
| “把这个闪念做成永久卡” | form-permanent |
| “看看哪些闪念该处理了” | review-process |
| 表达闪念同时附带网页 | capture-flash |

### C. Workflow Eval

用四象限验证深度：

- 小 × 充分：不进行无意义检索和深聊；
- 小 × 不充分：轻量展开；
- 大 × 充分：检索相关上下文并恢复结构；
- 大 × 不充分：允许深度检索、逐点展开和完整校验。

还需覆盖：

- 用户修正后返回展开；
- 成形即停；
- 不自动转永久卡；
- 暂停 / 恢复 / 放弃按需加载情况规则。

### D. Fact-source Drift Test

用变更反推边界是否真正解耦：

- CLI 参数改变 → 不应要求改 Skill 认知流程；
- manifest 字段名改变 → 不应要求改 Skill 认知流程；
- 四象限判断标准改变 → 不应要求改 CLI；
- 系统级作者权原则改变 → 不应在六个 Skill 维护六份完整副本。

## Phase 4：审计其他 Skill

按顺序审计：

1. `goodidea-form-permanent`
2. `goodidea-record-literature`
3. `goodidea-review-process`
4. `goodidea-connect-cards`
5. `goodidea-lint`

每个 Skill 回答：

- Intent 是什么？
- 主 State Machine 是什么？
- Completion Contract 是什么？
- 哪些内容应进入 reference？
- 哪些内容属于 CLI / schema？
- 哪些规则与 AGENTS / 其他 Skill 重复？
- metadata 是否只做路由？

逐个迁移，不做一次性大爆炸重构。

---

# 十四、闪念 Skill 实施任务清单

Agent 执行 Phase 2 时按以下顺序：

## Task 1：建立当前事实映射

审计现有 `goodidea-capture-flash/SKILL.md`，将每一段标记为：

- metadata / trigger
- AGENTS invariant
- schema contract
- main workflow
- reference: positioning
- reference: expansion
- reference: situations
- CLI technical detail
- test-only assertion
- obsolete / duplicate

先分类，后改写。禁止直接边读边删。

## Task 2：写新版 SKILL.md

新版必须以六步主状态机为骨架。

要求：

- 一眼能看出正常路径；
- 主流程优先于特殊情况；
- 每个状态明确进入条件、目标、退出条件；
- 明确用户决策点和 Agent 决策点；
- 需要详细知识时显式指向 reference；
- 不复制 reference 正文。

## Task 3：创建三个 references

按本文第八节建立：

- `positioning.md`
- `expansion.md`
- `situations.md`

优先迁移现有已经确认的规则，不在迁移过程中擅自创造新的产品决策。

遇到旧规则与 2026-08-23《闪念Skill重设计方案》冲突时，以后者的单主线与矩阵思想为目标设计；如涉及作者权、状态或数据不变量，继续服从 `AGENTS.md` / `schema.md`。

## Task 4：精简 openai.yaml

- 保留 display metadata；
- `default_prompt` 不再定义完整工作流；
- 不维护字段与 finalize 的第二份规则。

## Task 5：移除技术重复

从主 Skill 删除：

- 完整 CLI flags；
- manifest 字段字典；
- runtime 文件路径细节；
- 已由 schema / CLI 唯一定义的机器事实。

如 CLI `--help` 无法让 Agent 正确完成调用，优先补 CLI help，而不是把参数手册重新塞回 Skill。

## Task 6：调整验证

运行并补齐：

- `scripts/validate-skills.py`
- Skill 静态契约测试
- routing eval
- 四象限 workflow cases
- 与 capture CLI 相关的定向回归

如果变更没有触及执行语义，不得为了“检查很多”而把无关全量测试当成主要完成证据；验收应与风险映射对应。

## Task 7：差异审计

最终逐条检查：

- 是否仍存在“普通 / Plus”双主流程；
- 是否仍把“重要”作为流程分叉依据；
- 是否仍在主 Skill 维护 CLI 参数手册；
- 是否仍在主 Skill 维护 manifest 字段字典；
- 是否低频情况仍淹没正常流程；
- 是否 metadata 与 Skill 重复；
- 是否 references 中出现系统级宪法副本；
- 是否任何已有用户确认规则在迁移中丢失。

---

# 十五、完成标准

本次重构只有同时满足以下条件才算完成。

## 架构完成

- Skill 形成明确的 Discovery → Orchestration → Resources 渐进式披露；
- 每条事实有清楚 owner；
- `SKILL.md` 回归认知流程控制器；
- detailed method、exception、CLI、schema 不再混为一层。

## 闪念行为完成

- 所有闪念走统一六步主线；
- 规模 × 充分度决定处理深度；
- 小 × 充分不会被强制深聊；
- 大 × 不充分能够找到上下文并展开；
- Agent 能恢复逻辑连接而不是平铺要点；
- 用户拥有校正和最终去向决定权；
- 捕获阶段不自动升级永久卡。

## 解耦完成

- 修改 CLI 参数不要求改认知工作流；
- 修改 schema 字段不要求改认知工作流；
- 修改认知方法不要求改 CLI；
- metadata 不复制业务规则；
- tests 只验证，不成为隐性产品定义来源。

## 可持续完成

后续任何人准备往 `SKILL.md` 增加新规则时，都能使用本文“信息归位算法”明确回答：

> **这条信息是谁的职责？模型什么时候第一次需要知道它？**

回答不清楚时，不允许直接继续向主 Skill 堆内容。

---

# 十六、目标形态

最终架构：

```text
用户表达
   │
   ▼
Skill Metadata
“我该不该来？”
   │
   ▼
SKILL.md
“下一步做什么？何时分支或停止？”
   │
   ├───────────────┬────────────────┐
   ▼               ▼                ▼
positioning     expansion        situations
怎么判断         怎么展开          特殊情况
   │               │                │
   └───────────────┴────────────────┘
                   │
                   ▼
               CLI / Code
                准确执行
                   │
                   ▼
               正式系统状态

横向约束：
AGENTS.md  → 人机宪法
schema.md  → 数据与状态契约
Tests/Eval → 证明边界与行为没有失效
```

最终原则只有两条：

> **每条信息只属于一个事实源。**

> **模型只在第一次真正需要某条信息时，才看到它。**

这两条一旦成立，Skill 会自然变短，references 会自然形成，CLI 会自然独立，测试也会清楚自己究竟应该证明什么。
