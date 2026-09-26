---
id: "INT-20260825-3a9570cd"
type: "有意思"
title: "球球Token AI 中转站（生图 API 来源候选）"
status: "待处理"
created_at: "2026-08-25T13:50:58+08:00"
updated_at: "2026-08-25T13:50:58+08:00"
source_ids: []
---
# 球球Token AI 中转站（生图 API 来源候选）

## 原始记录

qiuqiutoken.com「球球Token」：New API 架构的 AI 接口中转站，国内直连免魔法网络，注册送 $5 试用额度。生图能力：站内开启 Midjourney 模块、支持 gpt-image 系列，全模态宣称 30+ 模型。OpenAI 兼容 base_url：https://qiuqiutoken.com/v1。2026-08-25 实测确认可访问（/api/status 返回 New API 状态、midjourney 模块开启）；尚未注册、无 API key。后续接入：注册 → 控制台创建 token → Hermes image_gen openai provider 配置 OPENAI_API_KEY + OPENAI_BASE_URL=https://qiuqiutoken.com/v1。接入步骤详见 ~/.hermes/accounts/qiuqiutoken.md。

## 产生情境

松海 2026-08-25 要求探测该中转站，确认可用后保存，后续作为生图 API 来源
