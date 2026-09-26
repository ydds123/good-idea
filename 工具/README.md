# 可选执行能力

`工具/` 是可删除、可替换的默认执行实现，不是产品规则来源。规则、对象身份和协作结果以 `规则/` 为准；脚本只搬运文件、校验格式、报告错误和调用 Git。

## 捕捉契约

```text
python3 工具/capture.py start --session <id> --title "<标题>" [--resume <路径>]
python3 工具/capture.py append --session <id>   # stdin: JSON 数组
python3 工具/capture.py stop --session <id>
python3 工具/capture.py status --session <id>
```

事件必须包含 `speaker`、`time`、`text`；可选 `turn_id` 只用于上游排查。写入按“时间＋说话人＋原文”精确去重，失败写 stderr 和 `.goodidea/tools.log`。未登记的 session 静默返回 0，便于适配器安全旁路。

`stop` 只标记 closing，仍可接收最后一回合事件；当前没有平台适配器时，Agent 可手工调用 `append`，脚本也不可用时按模板写入同样的 Markdown 记录。

## 新建和提交

```text
python3 工具/new.py <interesting|action|flash|permanent|source> "<标题>"
python3 工具/commit.py <记录路径> [--message "<提交说明>"]
```

新建脚本只复制模板、清理占位说明、处理日期和同名后缀；提交脚本只提交指定路径。删除任一脚本后，可按 `数据/README.md`、模板和当前规则手工完成同样结果。Git 失败不影响记录写入。

## 平台适配器

平台专有适配器预留在 `工具/hooks/`。Hermes 的事件格式、钩子注册方式和阶段 0 探针结果尚未在当前环境验证，因此没有伪造适配器或配置。
