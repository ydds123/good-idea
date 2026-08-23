# Good idea Skills 诊断报告

> 文档性质：现状诊断与设计依据，**非生效规则**。由松海发起，使用 yao-meta-skill（Skill OS 2.0）方法论对 `.agents/skills/` 做只读审查后落盘（2026-08-23）。作为《Good idea Skill 架构优化问题定义》方案的独立证据材料；与方案评估结论互证，不替代方案本身。

## 一、背景

松海正在推进 Good idea Skill 架构优化（《Good idea Skill 架构优化问题定义》），方案提出四类现状问题：Skill 职责边界不清晰、同一规则存在多个事实来源、Skill 缺少状态机表达、信息加载不符合 Agent 工作特点。为获得独立方法论侧的验证，调用 yao-meta-skill（`~/.codex/skills/yao-meta-skill`，Yao Meta Skill / Skill OS 2.0）对 6 个项目 Skill 做诊断审查。

## 二、审查方法与对象

审查框架（yao-meta-skill 方法）：

- **Trigger Lab**：触发描述是否含 recurring job + trigger actions + exclusions；与 AGENTS.md 任务路由表的一致性；近邻误路由风险
- **Boundary**：边界四问——owns what job / produces what outputs / near-neighbor exclusions / what detail belongs outside SKILL.md
- **Context Budget**：初始加载量、预算档位、质量密度（低频规则是否稀释核心流程）
- **Skill IR 六问**：owns what / when trigger / when not trigger / which resources carry behavior / which evals prove contract / which targets consume without semantic loss
- **Skill Atlas**：路由冲突、陈旧 skill、owner 缺口、多事实来源
- **Output Lab**：有无 skill vs 无 skill 的输出对比证据、触发盲测、路由评测

审查对象（`/Users/apple/Documents/good-idea/.agents/skills/`）：

| Skill | 大小 | 行数 |
|---|---|---|
| goodidea-capture-flash | 13,474B | 112 |
| goodidea-form-permanent | 13,201B | 85 |
| goodidea-record-literature | 6,250B | 59 |
| goodidea-connect-cards | 2,933B | 43 |
| goodidea-lint | 1,496B | 26 |
| goodidea-review-process | 1,090B | 21 |

每个 skill 目录仅含 `SKILL.md` 与 `agents/`（openai.yaml 展示模板），**无 references/ 附档目录**。

## 三、总体结论

**路由层合格，结构层阻塞。** 6 个 skill 的触发描述与边界设计达到 Trigger Lab 通过标准；但每个 skill 是"单文件信息堆"：Context Budget 阻塞（全量加载、无分级）、Boundary 阻塞（SKILL.md 承载了应外置的低频规则）、Output Lab 缺失（无任何输出/路由评测证据）、Skill Atlas 警示（同一规则多处维护，跨系统副本漂移）。诊断与《Good idea Skill 架构优化问题定义》的问题 1/2/4 完全互证。

## 四、P1 阻塞级问题

### P1-1｜SKILL.md 单文件过载，无 references/ 分层

- **问题**：违反 yao 方法论第一原则 "Keep SKILL.md lean; put guidance in references/, logic in scripts/, evidence in reports/"。capture-flash 13.4KB 混装 6 大块：多轮捕获工作流、闪念 Plus、暂停/恢复/放弃、单次轻量记录、讨论记录与结论沉淀（低频）、待办摄入澄清+四段信息架构+CLI 参数先查（低频）。form-permanent 13.2KB 混装草稿写作质量三机制（补充知识性质）与主流程。
- **证据**：`.agents/skills/goodidea-capture-flash/SKILL.md`（112 行）章节列表；`.agents/skills/goodidea-form-permanent/SKILL.md`（85 行）「草稿写作质量（2026-08-13 教训沉淀）」节；目录结构无 references/。
- **影响**：Agent 每次进入场景全量背负低频规则，核心流程被稀释（Context Budget 超档）。即方案问题 1（职责边界不清晰）+ 问题 4（信息提前加载）的实锤。
- **最小修正**：SKILL.md 只留主流程 + 判断节点 + 触发/排除；`待办摄入澄清`、`讨论记录机制`、`草稿写作质量`等低频规则移入 `references/`（如 `references/todo-intake-2026-08.md`），SKILL.md 保留一行指针。

### P1-2｜Output Lab 完全缺失——无 eval 证明 skill 能让 Agent 干对活

- **问题**：没有任何"有 skill vs 无 skill"的输出对比证据、触发盲测/对抗性 holdout、上下文预算检查。
- **证据**：`tests/` 现有 test_skills.py / test_skill_routing.py / test_skill_validator.py 与 `scripts/evaluate-skill-routing.py` 均为结构/路由静态校验，且按 AGENTS.md 只在修改 description 时才运行 evaluate-skill-routing.py；无行为级 eval 设施。
- **影响**：Skill IR 六问中 "Which evals prove the contract?" 无答案——skill 行为质量靠感觉不靠证据；方案「验证范围」缺验收判据与此同根。
- **最小修正**：为 capture-flash 建 3-5 个真实捕获场景 fixture（口述样本 → 期望 propose/finalize 序列），跑有/无 skill 对比，结果进 `reports/`（yao Output Lab 模式）。

## 五、P2 影响级问题

### P2-1｜同一规则三处维护，无 Skill Atlas 值守

- **证据**："捕获会话讨论存档""待办摄入澄清"等规则同时存在于：项目 SKILL.md、schema.md、Hermes 侧 `goodidea-development` skill（~/.hermes/skills/goodidea/，约 20KB + 22 个 references，内容高度重叠）；另有 AGENTS.md 任务路由表 ↔ skill description 双写路由。git log 显示两侧各自演进（2026-08-15 讨论存档机制两侧均有记录）。
- **影响**：即方案问题 2（同一规则多个事实来源）实锤，且比方案认知多一个副本（Hermes 侧）。
- **最小修正**：建规则归属表（每条规则唯一真源位置），定 Hermes 侧 skill 去留（收敛为开发态知识/教训库）。

### P2-2｜Skill IR 缺失：无平台中立契约，多消费方靠人肉保证语义一致

- **证据**：消费方至少 4 个——Hermes（terminal cat 全文）、Claude Code / Codex（~/.claude/skills、~/.codex/skills 均活跃）、Obsidian agent-client。项目 skill 无 skill-ir/ 契约文件、无多平台适配层；agents/openai.yaml 仅为展示模板（display_name/short_description/default_prompt），不含行为语义。
- **影响**：同一 skill 在不同平台的"何时触发/何时不触发"无机器可读单一表达，新增入口时语义漂移无法检测。
- **最小修正**：用 yao 的 `skill-ir/schema.json` + `scripts/export_skill_ir.py` 为 6 个 skill 生成 skill-ir/ JSON（job/trigger/exclusion/eval plan），作为跨平台语义基准。

## 六、P3 优化级

- **P3-1｜lint / review-process 无排除条款**：职责单一风险低，可补"不处理内容判断/不替代其他 skill"式排除，防近邻误路由。
- **P3-2｜frontmatter 缺治理元数据**：仅 name+description，无 version/owner/maturity/review cadence；至少加 `version` 与 `updated_at`。
- **P3-3｜description 偏长（100+ 字）**：job+trigger+exclusion 齐全可接受，但触发动作词建议前置，便于路由评测量化。
- **P3-4｜无 Context Budget 测量**：记录每个 SKILL.md 初始加载 token 数（capture-flash 现约 6-7K tokens），重构后对比，可作为渐进加载生效的量化指标（可作方案验收判据之一）。

## 七、通过项（不应改动）

- **Trigger Lab 6/6 通过**：description 均含 job+trigger+exclusion，与 AGENTS.md 任务路由表 8 行完全对齐，无路由孤儿、无缺 skill。
- **近邻边界清楚**：capture-flash ↔ record-literature（"正在表达想法即使带链接也归 capture-flash"）、form-permanent（"以后可以成卡"不触发）、connect-cards（"不补做准入门禁"）——yao Trigger Lab 高分样板。
- **轻量门禁已存在**：validate-skills.py（YAML 校验）、evaluate-skill-routing.py、test_skill_*.py。
- **交叉引用一致**：skill 间交接指向全部正确。
- **Trust 通过**：无外部脚本注入、无不可信内容，命令均为自有 CLI。

## 八、与《Good idea Skill 架构优化问题定义》的互证

| 方案问题 | yao 诊断 | 互证结论 |
|---|---|---|
| 问题 1：Skill 职责边界不清晰 | P1-1 单文件过载无分层 | 方向成立，且"缺 references 分层机制"是根因之一 |
| 问题 2：同一规则多事实来源 | P2-1 三处维护 + Hermes 侧副本 | 成立且比方案认知更严重 |
| 问题 4：信息提前加载 | P1-1 Context Budget 超档 | 成立，缺"渐进加载机制"（AGENTS.md 还要求完整读取） |
| 问题 3：缺状态机表达 | 未直接验证 | 需方案层面另行确认（Skill 流程状态 vs CLI 数据状态） |
| 验证范围无判据 | P1-2 Output Lab 缺失 | 同根：系统无 skill 级 eval 设施 |

核心洞察：**skill 层是系统里唯一没有工程化托底的层**——CLI 有状态机/事务/测试/回滚，skill 只有纯文本约定。重构方向不是重写 skill 内容，而是给 skill 层补上分层机制（references）、行为证据（eval）、唯一真源（归属表）三件基础设施。

## 九、后续工作（2026-08-23 松海确认）

### 9.1 待办内容错位（松海指出的具体案例）

capture-flash 中「待办摄入澄清（B 原则/四问）」与「待办卡片四段信息架构（标题/事项/动机/情境）」「CLI 参数先查」属于**待办场景**流程，却埋在闪念 Skill 内——结构错位实证。Skill 重构时应拆出：独立待办 Skill（或明确归属），使 capture-flash 只保留"用户正在表达想法"的主流程。

### 9.2 Skill 维护门禁（松海拍板）

后续对 `.agents/skills/` 的新增、迭代、删除，**默认调用 yao-meta-skill 审查流程，禁止 Agent 直接改**：Trigger Lab（触发描述）→ Boundary（SKILL.md 只留主流程，低频规则进 references/）→ Context Budget（加载量）→ Output Lab（行为改动附证据）四关自查，改完跑 `scripts/validate-skills.py` + 相关测试。已落地于 Hermes 侧 goodidea-development skill「Skill 维护门禁」节；项目侧（AGENTS.md）跨平台生效待定。

## 附：审查工具

- yao-meta-skill：`/Users/apple/.codex/skills/yao-meta-skill`（与 `~/.claude/skills/yao-meta-skill` 同源），VERSION 文件记录版本
- 本次审查为只读诊断，未修改任何项目文件
