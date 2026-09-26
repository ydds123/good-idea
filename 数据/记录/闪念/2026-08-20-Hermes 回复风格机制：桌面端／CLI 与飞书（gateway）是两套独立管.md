---
status: "待辨析"
---

# Hermes 回复风格机制：桌面端/CLI 与飞书（gateway）是两套独立管

## 核心内容

Hermes 回复风格机制：桌面端/CLI 与飞书（gateway）是两套独立管线——display.personality（当前 kawaii）仅 CLI/桌面端注入；gateway 源码明确 personality 是 CLI-only（display_config.py:30），只经 ephemeral system prompt 兜底且 ephemeral_system_ttl=0 不生效，故飞书保持正常风格。gateway 进程 8-15 启动未重启（launchd ai.hermes.gateway），8-18 更新 v0.20.4 后若重启 gateway，新代码可能开始注入 personality，飞书也会变 kawaii——届时先改 display.personality 再重启，两端统一。

## 产生情境

2026-08-20 桌面端会话：松海发现桌面端回复变 kawaii（display.personality: kawaii 2026-07-11 即已配置，近期更新后才真正生效），追问飞书为何风格不同；排查 gateway 进程启动时间/display_config.py/ephemeral system prompt 路径后确认两套管线机制。松海要求先记录本情况，届时与 Good idea 里关于消息推送的回复风格关联起来。
