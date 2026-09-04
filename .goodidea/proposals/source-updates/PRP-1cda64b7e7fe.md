---
id: "PRP-1cda64b7e7fe"
type: "source_update_proposal"
title: "来源更新候选：苹果前 AI 设计主管复盘：如何让 AI 彻底摆脱“工业垃圾”审美，做出顶尖设计？"
status: "待处理"
created_at: "2026-09-04T20:17:38+08:00"
updated_at: "2026-09-04T20:17:38+08:00"
---
# 来源更新候选：苹果前 AI 设计主管复盘：如何让 AI 彻底摆脱“工业垃圾”审美，做出顶尖设计？

## 候选内容

待确认

## 机器数据

<!-- goodidea:proposal-json:start -->
{
  "new_content_sha256": "b2b81c02a7d04eaa08fde25e8dde6fa3442baffee8047b272f2191bd55a5917c",
  "old_content_sha256": "a75a166605a7f513f9ef0bb057a0d34b98a73e43f3c518453c1b36b454dc6af5",
  "preview": {
    "author": "MCFON",
    "canonical_url": "https://mp.weixin.qq.com/s/Ve4dfvHfkYfgVLKAP-qJ1w",
    "error": "",
    "extractor": "agent-markdown",
    "images": [
      {
        "alt": "图1",
        "referer": "https://mp.weixin.qq.com/s/Ve4dfvHfkYfgVLKAP-qJ1w",
        "url": "https://mmbiz.qpic.cn/mmbiz_png/5x4eWsmGCfFrPnuLAlHV5bWkAZn70Ex3MPs70EcVC7icznwHakzTJibQPtLq4qupajmalf319B6NKdTEKIYIEbekXhA3JrJ4x7kLUH57dUPlY/640?from=appmsg"
      },
      {
        "alt": "图2",
        "referer": "https://mp.weixin.qq.com/s/Ve4dfvHfkYfgVLKAP-qJ1w",
        "url": "https://mmbiz.qpic.cn/sz_mmbiz_png/5x4eWsmGCfHV3Gb410y76At9Mr3G0SFSXxWXiaSsX1eGfSLNuibOYlPuH0ibqCsvBTrPMMQ4CAfhFR7ZBLdAyywpQxtiaCu7XmvFpLfNiaELHop4/640?from=appmsg"
      },
      {
        "alt": "图3",
        "referer": "https://mp.weixin.qq.com/s/Ve4dfvHfkYfgVLKAP-qJ1w",
        "url": "https://mmbiz.qpic.cn/mmbiz_png/5x4eWsmGCfGgHCCiamC5BuEX5czg19ZT5vk0QMt40xarxTHMUYLiaAw4AL4uKaCCbRZmRicWwgHh7Sm9t3uoNDlQN4MPR1W0EicXOZ3g35TL3Xw/640?from=appmsg"
      },
      {
        "alt": "图4",
        "referer": "https://mp.weixin.qq.com/s/Ve4dfvHfkYfgVLKAP-qJ1w",
        "url": "https://mmbiz.qpic.cn/sz_mmbiz_png/5x4eWsmGCfGMh5XpzFMfaJiaf7M6BBt6wkE0tT42RgGgr2J62LoLDniahF6NnFxIicpNERRZutiaCSkQLgfXpgN8wPAMdV9hQU8F2F7ApfT5cAg/640?from=appmsg"
      },
      {
        "alt": "图5",
        "referer": "https://mp.weixin.qq.com/s/Ve4dfvHfkYfgVLKAP-qJ1w",
        "url": "https://mmbiz.qpic.cn/mmbiz_png/5x4eWsmGCfHXYhkbRevsJfncL0HJynwuTPeLG0rBDTAQsVzUsibe9PZGhvvnIxxra3VWRqvMClAlP5hibtebiagdNuxKU5nP20ZemtjLlSUohw/640?from=appmsg"
      }
    ],
    "markdown": "导读：大模型本质是下一个 Token 的概率预测器，做设计决策时天然偏向迎合大众的最大公约数，导致未经深度引导的 AI 设计几乎必然沦为平庸的“工业垃圾”——左文右图、紫色渐变、毫无灵魂。\n\n曾领导苹果未来 AI 产品研发与原型设计 12 年的 Anshu Chimala 近日在硅谷顶流专栏 Lenny's Newsletter 发布万字复盘，公开了他调教 AI 的独家“双钻设计框架”：通过随机种子破局、独立设计评审智能体闭环、多模态视频微动效注入，以及苹果级的无情做减法，将 AI 的创造力释放至 99%，让人人都能指挥 AI 做出工作室级的惊艳作品！\n\n01 为什么你的 AI 设计总是“工业垃圾”？\n\n在过去一年里，你一定无数次尝试过让 Claude 、 GPT 或各类前端 AI 助手设计网页或 App 。但绝大多数时候，交付的成果令人沮丧：\n\n* 永远是千篇一律的淡紫色或蓝色渐变背景；\n\n* 永远是左侧大标题加按钮、右侧一张插图的呆板布局；\n\n* 毫无质感的花哨发光卡片、冗长而空洞的占位文案。\n\n为什么顶级设计师用 AI 能在几轮对话内做出令人拍案叫绝的界面，而普通人得到的却总是千篇一律的“通用工业垃圾（ Generic Slop ）”？\n\n曾领导苹果未来 AI 产品原型设计 12 年的 Anshu Chimala 揭示了一个残酷的底层逻辑：这是大模型底层原理与顶级设计哲学之间的天然冲突。\n\n![图1](https://mmbiz.qpic.cn/mmbiz_png/5x4eWsmGCfFrPnuLAlHV5bWkAZn70Ex3MPs70EcVC7icznwHakzTJibQPtLq4qupajmalf319B6NKdTEKIYIEbekXhA3JrJ4x7kLUH57dUPlY/640?from=appmsg)\n\n1. 大模型的宿命：迎合所有人的“委员会妥协”\n\n大型语言模型（ LLMs ）本质上是下一个 Token 的概率预测器（ Next-token Predictors ）。\n\n在自回归生成时，模型每一步都在基于海量预训练数据与 RLHF 人类对齐偏好，计算“最符合大众期望”的安全选择。\n\n当模型面临设计决策——该用什么配色？如何安排留白？组件如何排列？——它会本能地选择概率最高、风险最小、最不容易挨骂的折中方案。 其结果就是终极的“委员会设计（ Design-by-committee ）”：安全、合规，但极其平庸、寡淡无味。\n\n2. 顶尖设计的本质：打破预期的情感触动\n\n真正的伟大设计（如 Apple 、 Braun 、 Dyson 的经典作品）从来不是概率最大化的产物。优秀的设计始于感觉，旨在引发强烈的情感共鸣；它打破常规、挑战认知、用克制而意想不到的细节带给用户惊喜。\n\n换言之：顶级设计所追求的“反常识与高惊喜度”，恰恰是大模型自回归生成本能的反面。\n\n如果我们只是简单地对 AI 说“帮我做个好看的极简网页”，模型就会立刻退回它的“安全平庸舒适区”。想要释放 AI 隐藏在概率冰山之下的另外 99% 创造力，必须引入一套严密的AI 协同设计流水线。\n\nAnshu 将经典的双钻设计模型（ Double Diamond ）全面重构为针对 AI 智能体团队的全新工作流：\n\n1. 发散探索（ Discover ）：跳出平庸默认值，探索广袤的可能性边界；\n\n2. 深化聚焦（ Define ）：引入外部对抗与多模态资产，赋予设计独立灵魂；\n\n3. 交付打磨（ Deliver ）：无情做减法，剔除一切 AI 痕迹，达到工业级克制。\n\n02 阶段一 · 发散探索（ Discover ）：打破大模型的平庸舒适区\n\n面对一片空白的屏幕，大模型最容易直接套用它最熟悉的模板。在这个阶段，核心目标是逼迫 AI 走出舒适区，以低成本探索足够发散的视觉方向。\n\n技法 1 · Seed Strings （随机种子字符破局法）\n\n很多人以为只要在提示词里加上“做个完全随机、独一无二的设计”， AI 就会带来惊喜。但实验表明，即使你要求“完全随机”， Claude 或 GPT 给出的依然是同一套紫色渐变，只是文案稍微变了变——因为模型本质上无法在内部产生真正的随机性。\n\nAnshu 借鉴了 Sakana AI 的研究成果，提出了 Seed Strings （随机种子思维链） 技法：\n\n通过外部环境（ Shell 脚本）生成一串纯随机的字母数字哈希值，要求模型以此为灵感锚点推导设计方向！\n\n【实战 Prompt · 随机种子破局法】 我想让你为我的生产力工具设计一个落地页。  请按以下步骤执行： 1. 使用 Shell 脚本生成一段较长的随机字母数字字符串（如 `openssl rand -hex 16`）； 2. 仔细观察这段随机字符中的潜在模式、特殊数值与隐藏结构，以此为灵感定义你的创意方向（配色方案、布局律动、字体排印与视觉张力）； 3. 运用你的专业判断力将这一创意方向落地，并使其兼具美感与功能性； 4. 切勿在最终设计中展示这串字符，它仅作为你潜意识的灵感源泉。\n\n![图2](https://mmbiz.qpic.cn/sz_mmbiz_png/5x4eWsmGCfHV3Gb410y76At9Mr3G0SFSXxWXiaSsX1eGfSLNuibOYlPuH0ibqCsvBTrPMMQ4CAfhFR7ZBLdAyywpQxtiaCu7XmvFpLfNiaELHop4/640?from=appmsg)\n\n如上图所示，当被剥离了“默认概率路径”后，模型开始做出令人意想不到的大胆选择：复古打字机配色、极具张力的大号衬线字体、非对称排版……每一轮生成都是真正独一无二的原生设计！\n\n技法 2 · 野心提示词与人类品味注入（ Ambitious Prompts ）\n\n大模型缺乏生活体验，它不知道什么叫“质感”。你必须将自己的人类品味（ Human Taste ）作为高维度输入强行注入系统：\n\n* 将工业设计、复古街机、现代建筑、美术馆装置艺术作为设计的隐喻底色；\n\n* 三步提纯法：\n\n1. 广泛发散：让 AI 列出 20 个大跨度、粗颗粒度的风格概念（如“重型工业控制台”、“等距立体赛博城市”），不要求细节；\n\n2. 人类审美批注：挑选你心动的方向，写下真实感知（“我想要沉重的触觉按键声与阻尼感，但不要廉价的拟物塑料风；需要真实拉丝金属材质，而不是灰色渐变”）；\n\n3. 固化生产级 Prompt：让 AI 结合你的批注，反向编写出精准、富有工程细节的执行提示词。\n\n03 阶段二 · 深化聚焦（ Define ）：赋予设计独立的灵魂与个性\n\n初稿生成后，往往空有骨架但缺乏细节。如果我们直接对当前写代码的 Agent 说“请继续优化这个设计”，通常毫无作用——因为写代码的 Agent 是自己作品的创作者，它深陷在自己的实现逻辑与局部思维中，无法客观跳出视角（ Think Different ）。\n\n技法 3 · 设计评审子智能体正反馈循环（ Design Critic Subagent Loop ）\n\n苹果设计团队最核心的文化是严苛的设计评审（ Design Review ）。在 AI 时代， Anshu 将这一机制固化为一个独立的双智能体对抗系统：\n\n* 执行 Agent （ Worker ）：负责写代码、构建 UI ，由高性价比模型担任；\n\n* 设计评审 Agent （ Critic ）：引入逻辑推理极强的旗舰大模型（如 Claude Opus 5 / GPT-5.6 ），仅看渲染截图，完全隔离代码上下文，按世界顶尖设计工作室的标准以 10 分制客观打分，不到 9 分决不放行！\n\n![图3](https://mmbiz.qpic.cn/mmbiz_png/5x4eWsmGCfGgHCCiamC5BuEX5czg19ZT5vk0QMt40xarxTHMUYLiaAw4AL4uKaCCbRZmRicWwgHh7Sm9t3uoNDlQN4MPR1W0EicXOZ3g35TL3Xw/640?from=appmsg)\n\n【实战 Prompt · 设计评审 Critic 智能体配置】 我想让你进一步优化当前设计。为了找准发力点，请调用一个独立的旗舰大模型子智能体作为“设计挑剔官（Design Critic）”。  在每次迭代中严格遵循以下闭环： 1. 截取当前界面的无损全屏渲染截图； 2. 在全新的 Context 中唤起 Critic 智能体，只给它发送截图，严禁输入任何代码实现或上一轮的历史对话； 3. 要求 Critic 评估该界面正在尝试传达的美学风格，脑补一家全球顶尖独立设计工作室会如何极致诠释该风格，并逐项列出当前界面最大的审美差距； 4. 严格以 10 分制打分，客观衡量当前设计与工作室水准的差距； 5. 明确告知 Critic：重点惩罚那些滥用 AI 常见俗套（如廉价光效、重复卡片）的元素；只有当 Critic 给出 9 分以上时，任务才算交付。\n\n这种机制的绝妙之处在于：廉价模型负责繁琐的排版与代码编写，昂贵的高阶模型只在关键决策点提供审美品味，既节省了 90% 以上的 Token 开销，又彻底锁死了设计品质的下限！\n\n技法 4 & 5 · 引入原生多模态资产与物理微动效\n\n纯代码（ CSS / Canvas ）绘制的图形往往带有浓厚的“程序员塑料味”。顶级界面的另一大秘诀是多模态资产的降维打击：\n\n* 原生图像生成赋能：指示代码 Agent 通过内置 API 生成高精度 3D 渲染图、玻璃拟态材质与着色器贴图；\n\n* 物理视频模型生成无缝微交互：利用现代视频模型（如 fal.ai 上的 Seedance 等），生成带 Alpha 通道的循环背景动效（如水晶碎裂旋转与光线折射），甚至生成多状态关键帧视频片段，将其绑定到用户的滑动滚轮手势上，实现类似苹果官网般的丝滑交互体验。\n\n04 阶段三 · 交付打磨（ Deliver ）：无情做减法，达到苹果级克制质感\n\n在生成式 AI 领域，有一个几乎所有大模型都自带的通病：AI 极度擅长做加法，却从不会主动做减法。\n\nAI 害怕承担风险，删除代码和组件在它的概率模型里被视为高风险行为。因此， AI 交付的原型往往堆砌了无数无用的小组件、多余的说明文字和晃眼的发光边框。\n\n技法 6 · 无情做减法（ Cut Elements That Don't Add Value ）\n\nAnshu 在复盘中分享了他开发一款对话式卡路里追踪 App 的真实历程：\n\n![图4](https://mmbiz.qpic.cn/sz_mmbiz_png/5x4eWsmGCfGMh5XpzFMfaJiaf7M6BBt6wkE0tT42RgGgr2J62LoLDniahF6NnFxIicpNERRZutiaCSkQLgfXpgN8wPAMdV9hQU8F2F7ApfT5cAg/640?from=appmsg)\n\n在初版中，尽管明确要求了“极简”， Claude 依然塞进了大量无效元素：\n\n* 进度条和背景上廉价的粉色光晕；\n\n* 文字上随机的荧光高亮；\n\n* 列表展示每餐食物时堆砌了冗余标签，而图片本身就已经传达了信息；\n\n* 丑陋且不符合原生体验的自定义按钮。\n\nAnshu 给出的指令极其克制且坚定：\n\n1. 将布局彻底简化为以图片为核心的无边框网格；\n\n2. 彻底移除所有渐变色、发光特效与多余卡片容器；\n\n3. 全面使用 iOS 原生系统组件与纯粹排版，追求极致的 Apple-Native 呼吸感。\n\n![图5](https://mmbiz.qpic.cn/mmbiz_png/5x4eWsmGCfHXYhkbRevsJfncL0HJynwuTPeLG0rBDTAQsVzUsibe9PZGhvvnIxxra3VWRqvMClAlP5hibtebiagdNuxKU5nP20ZemtjLlSUohw/640?from=appmsg)\n\n改造后的结果令人惊艳：过度装饰荡然无存，视觉焦点完全回归到食物图片与核心数值本身，字号紧凑、信息层级清晰，展现出真正高级的工业美学。\n\n技法 7 · 剔除“AI 味”（ Remove AI Tells ）\n\n让专业设计师一眼识别出“这是 AI 做的”通常有几个致命标志（ Tells ）：\n\n* 缺乏主次的均等间距： AI 喜欢给所有模块设置相同的 Padding 和 Margin ，缺乏节奏感；\n\n* 毫无克制的阴影与圆角：动辄 border-radius: 24px 配合大面积弥散阴影；\n\n* 空洞的排版装饰：莫名其妙的星号、装饰线和占位图标。\n\n在交付前，必须下达明确的审查指令：消除一切不服务于核心功能的修饰，用更小、更紧凑的字阶，让界面在克制中流淌出高级感。\n\n05 总结与心法： AI 时代，人类设计师的终极护城河是什么？\n\n回顾 Anshu Chimala 的万字复盘，我们不难得出一个颠覆性的认知：\n\n在 Agent 能够几秒钟写出成百上千行前端代码的时代，决定设计上限的，从来不是编码速度，而是你的审美天花板。\n\nAI 时代的设计心法：\n\n1. 大模型是概率的俘虏，而艺术是对概率的反叛。绝不要指望默认状态下的 AI 能给你惊喜；\n\n2. 建立对抗机制：不要让写代码的 Agent 自己当裁判，让独立的 Critic Agent 站在用户与大师的视角冷酷挑刺；\n\n3. 极简不是空无一物，而是克制的精准。无情砍掉 AI 随手添加的 80% 视觉垃圾，剩下的 20% 才会闪闪发光；\n\n4. Taste is the new code （品味即代码）。 AI 抹平了技术实现的门槛，你脑海中对色彩、空间、节奏与情绪的深刻理解，才是不可替代的核心资产。\n\n本文深度编译与结构化复盘自 Lenny's Newsletter 专栏《 How to turn your AI into a world-class designer 》，作者 Anshu Chimala （前苹果 AI 研发团队主管、 YC 创始人）。",
    "published_at": "2026-09-03",
    "status": "complete",
    "tags": [],
    "title": "苹果前 AI 设计主管复盘：如何让 AI 彻底摆脱“工业垃圾”审美，做出顶尖设计？"
  },
  "source_id": "SRC-774eaa267132"
}
<!-- goodidea:proposal-json:end -->
