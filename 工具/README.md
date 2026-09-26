# 可选执行能力

本目录提供确定性搬运动作的默认实现，不定义产品规则。规则和数据即使没有本目录也成立；脚本不可用时，按对应 Skill、`数据/README.md`、模板和规则手工完成同样结果。

## `new.py`

创建正式记录空壳：

```text
python3 工具/new.py <类型> "<标题>"
```

类型为 `interesting`、`action`、`flash`、`permanent` 或 `source`。脚本从 `数据/模板/` 复制模板，按本地日期和标题命名，同名时追加 `-2`、`-3`，并在标准输出打印路径。脚本失败时不会创建半成品；手工退路是复制对应模板并按 `数据/README.md` 的命名约定创建文件。

## 捕捉能力契约（当前默认实现：`capture.py`）

```text
python3 工具/capture.py start --session <id> --title "<标题>" [--resume <已有记录路径>]
python3 工具/capture.py append --session <id> < events.json
python3 工具/capture.py stop --session <id>
python3 工具/capture.py status --session <id>
```

`append` 接收 JSON 数组，事件必须包含 `speaker`、`time`、`text`，可带 `turn_id`。写入前解析目标记录中的完整消息，按“时间＋说话人＋原文”精确去重，不依赖 `.goodidea/` 状态。失败原因写入标准错误和 `.goodidea/tools.log`；未知会话也会记录日志。能力不可用时，按原始思考记录模板手工追加可见消息。

## 版本提交能力（可选）

`commit.py <记录路径>` 只提交指定记录及必要的版本变更。删除或禁用它不会影响记录写入；提交失败时保留未提交记录，并由 `status` 呈现。脚本不得使用宽泛的 `git add .`，不得带入工作区其他改动。

## 平台适配器

`hooks/` 只存运行时适配器。当前 Hermes 适配器尚未启用，须先完成运行时事件契约验证；适配器只把平台事件转换为通用捕捉事件，不向规则层写入平台字段。
