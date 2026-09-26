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

`stop` 标记 closing；下一次 `append`（即使事件全部重复）处理完后自动注销 session。当前没有平台适配器时，Agent 可手工调用 `append`，脚本也不可用时按模板写入同样的 Markdown 记录。

## 新建和提交

```text
python3 工具/new.py <interesting|action|flash|permanent|source> "<标题>"
python3 工具/commit.py <记录路径> [--message "<提交说明>"]
```

新建脚本只复制模板、清理占位说明、处理日期和同名后缀；提交脚本只提交指定路径。删除任一脚本后，可按 `数据/README.md`、模板和当前规则手工完成同样结果。Git 失败不影响记录写入。

## 平台适配器

`工具/hooks/hermes_post_turn.py` 是本机 Hermes 的默认适配器：只有它认识 Hermes 的字段和钩子机制，把每回合的用户可见消息和 Agent 最终可见回复转成通用事件数组，交给上面的捕捉契约；未登记的 session 静默旁路，失败写 `.goodidea/tools.log` 并返回非零，不阻塞回复。它不做产品判断，删掉本文件并移除钩子配置即禁用自动转录与自动提交，记录仍可读可写、由 Agent 手工补写。

本机注册位置和方式（只写接入方式，不写产品规则）：

```text
~/.hermes/config.yaml                     hooks: post_llm_call 段
~/.hermes/shell-hooks-allowlist.json      逐 (事件, 命令) 授权记录
```

```yaml
hooks:
  post_llm_call:
    - command: "python3 /Users/apple/Documents/Goodidea/工具/hooks/hermes_post_turn.py"
      timeout: 15
```

- 授权：用 `hermes chat --accept-hooks` 或 `hermes hooks` 子命令逐条记录；未授权的钩子不执行
- 生效时机：钩子在进程启动时注册，改配置后要重启对应入口（桌面端、CLI、网关）才生效
- 同步执行：回合结束会等钩子返回，所以适配器只做搬运，单次控制在几百毫秒内
- 只在成功且未中断的回合触发：中断或失败回合拿不到正文，这类回合的可见消息按捕捉契约手工 `append` 补写
- `工具/hooks/hermes_event_probe.py` 是核实事件契约用的探针，只写 `.goodidea/probe.log`，不属于执行契约
