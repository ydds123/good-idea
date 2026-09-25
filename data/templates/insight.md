---
id: INS-YYYYMMDD-NNN
status: active
created_at: YYYY-MM-DDTHH:MM:SS+08:00
current_version: 1
---

# 永久认识标题

## 当前版本

### 判断

能够脱离原对话独立理解的阶段性判断。

### 必要理由

让这项判断成立所必需的理由。

### 边界或不确定性

只有确实影响适用范围时才填写；没有则不制造内容。

### 形成依据

- `SES-YYYYMMDD-NNN`
- `FLA-YYYYMMDD-NNN`
- 有实际外部材料时再列 `SRC-YYYYMMDD-NNN#snapshot-N`

## 版本历史

### v1｜YYYY-MM-DD HH:MM｜用户认领

保存当时完整判断、理由、必要边界和形成依据。

后续修订追加新版本并更新 `current_version`；不要把生命周期状态改成 `revised`。停用时只把顶层状态改为 `retired`，版本历史继续保留。
