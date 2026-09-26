---
id: "SRC-f74994df3257"
type: "来源"
title: "Edgetunnel 部署运维与恢复手册"
status: "完整"
capture_status: "完整"
author: "松海"
published_at: ""
fetched_at: "2026-08-26T19:36:14+08:00"
created_at: "2026-08-26T19:36:14+08:00"
updated_at: "2026-08-26T19:36:14+08:00"
content_sha256: "f62a57543a5c10a7cc98e510ab42b8a39d308f0a261bbb64014a08d5e97b5c55"
image_failures: []
tags: ["梯子", "Edgetunnel", "Cloudflare"]
origin_filename: "Edgetunnel-部署运维与恢复手册.md"
origin_sha256: "f62a57543a5c10a7cc98e510ab42b8a39d308f0a261bbb64014a08d5e97b5c55"
snapshot_sha256: "0492c8d7c61223de19751570e804c9afd21ea967aa8dc0faa3cfd875d3dfafe2"
---
# Edgetunnel 部署运维与恢复手册

## 原文快照

<!-- goodidea:snapshot:start sha256=0492c8d7c61223de19751570e804c9afd21ea967aa8dc0faa3cfd875d3dfafe2 -->
> 作者：松海

> 建档日期：2026-08-26（Asia/Shanghai）  
> 用途：记录本次 Cloudflare Pages 部署的关键资源、入口、恢复方法和安全边界，避免以后忘记或误删。  
> 安全原则：本文档**不保存管理密码、UUID、订阅令牌或完整订阅链接的明文**。这些内容应从 Cloudflare 或管理后台查看和重置。

## 1. 当前状态一览

| 项目 | 当前状态 |
|---|---|
| 部署状态 | 已完成，生产环境访问正常 |
| 部署方式 | Cloudflare Pages 上传压缩包（Direct Upload） |
| Pages 项目名 | `edgetunnel-20260826` |
| 公开站点 | <https://edgetunnel-20260826.pages.dev> |
| 管理后台 | <https://edgetunnel-20260826.pages.dev/admin> |
| 未登录行为 | 访问 `/admin` 会跳转到 `/login` |
| 程序版本 | `v2.1.20260811` |
| KV 绑定 | 程序变量 `KV` → 命名空间 `EDT2` |
| 管理密码变量 | Pages 生产环境变量 `ADMIN` |
| 自定义域名 | 当前没有，直接使用免费的 `pages.dev` 地址 |
| 当前套餐 | Cloudflare Workers Free，当前无需充值 |

## 2. Cloudflare 资源定位

### 2.1 账户与项目

- Cloudflare 控制台：<https://dash.cloudflare.com>
- Cloudflare Account ID：`608c4f1ad1381eaada8f0dc8306ebcb0`
- Pages 项目：`edgetunnel-20260826`
- Pages 项目地址：<https://dash.cloudflare.com/608c4f1ad1381eaada8f0dc8306ebcb0/pages/view/edgetunnel-20260826>

进入路径：

1. 登录 Cloudflare。
2. 打开“计算和 AI”。
3. 进入“Workers 和 Pages”。
4. 选择 `edgetunnel-20260826`。

### 2.2 KV 命名空间

- 命名空间名称：`EDT2`
- Namespace ID：`5546636f9a22472cb0c38597ff898924`
- 程序使用的绑定名称：`KV`

KV 是项目的“小型配置仓库”，负责保存后台设置、节点配置、优选配置和订阅相关参数。它不是用来存储代理流量、视频内容或所有网络数据包的。

关系如下：

```text
Pages 程序中的 env.KV
          ↓
Cloudflare Pages 绑定关系：KV
          ↓
实际 KV 命名空间：EDT2
```

**不要删除 `EDT2`。** 删除后，网站代码可能还在，但管理后台保存的配置可能丢失，订阅和节点配置也可能异常。

## 3. 密码、订阅和敏感信息去哪里找

### 3.1 管理后台密码

本文档不保存密码明文。密码保存在 Pages 项目的生产环境变量 `ADMIN` 中。

查找路径：

1. Cloudflare → Workers 和 Pages。
2. 打开 `edgetunnel-20260826`。
3. 打开“设置”。
4. 找到“变量和机密”或“环境变量”。
5. 在生产环境中找到 `ADMIN`。

如果 Cloudflare 界面不再允许查看旧值，直接把 `ADMIN` 替换为一个新的强密码，然后执行一次新的生产部署，使新密码生效。

修改密码后的关键动作：

1. 修改生产环境中的 `ADMIN`。
2. 点击保存全部更改。
3. 重新上传部署包并部署到生产环境。
4. 用新密码登录 `/admin` 做实际验证。

不要只修改变量而不重新部署；本项目按照当前教程和部署方式，需要重新部署才能确保变量在生产版本中生效。

### 3.2 节点 UUID、订阅地址和订阅令牌

在管理后台查看：

- <https://edgetunnel-20260826.pages.dev/admin>

登录后可以看到节点信息、订阅信息和相关配置。不要把以下内容发到公开群聊、论坛、截图或社交媒体：

- 管理密码；
- 节点 UUID；
- 完整订阅地址；
- 订阅令牌；
- 后台完整截图；
- Cloudflare 登录信息和 API Token。

一旦怀疑订阅链接或 UUID 泄露，应在后台更换相关值、保存配置，并重新更新客户端订阅。

## 4. 本次部署使用的源文件

- GitHub 项目：<https://github.com/cmliu/edgetunnel>
- 本地部署压缩包：`/Users/apple/Documents/Codex/2026-08-26/https-x-com-qt9277-status-2071759371655152095/work/downloads/edgetunnel-main.zip`
- 压缩包 SHA-256：`870b12f50f44497c8e823c14dfcc4662fc2c11ddad70e35876980ad869e869ed`
- 下载时对应的 Git 提交：`e2da274be4148fb2f7d3ded10ce510157084a8df`
- 管理后台显示版本：`v2.1.20260811`
- 参考教程：<https://fastly.blog.cmliussss.com/p/edt2/>
- 原始帖子：<https://x.com/QT9277/status/2071759371655152095>

SHA-256 用来确认以后拿到的压缩包是否和本次上传的是同一个文件。文件内容有任何变化，SHA-256 都会不同。

## 5. 重新部署或升级的安全流程

### 5.1 只是重新部署当前版本

1. 确认 `EDT2` KV 命名空间仍然存在。
2. 确认 Pages 生产环境仍有：
   - `ADMIN`：管理密码；
   - `KV`：绑定到 `EDT2`。
3. 在 Pages 项目中创建新部署并上传本次压缩包。
4. 等待生产部署成功。
5. 回归测试首页、登录跳转和管理后台。

### 5.2 升级到未来的新版本

不要直接覆盖后就结束，建议按以下顺序：

1. 从官方 GitHub 仓库下载新版本，不使用来历不明的压缩包。
2. 记录下载日期、版本、提交号和 SHA-256。
3. 不删除 `EDT2`，不随意重建 Pages 项目。
4. 部署新版本。
5. 检查变量 `ADMIN` 和 KV 绑定 `KV → EDT2` 是否仍然存在。
6. 实际测试：
   - 首页能否打开；
   - 未登录 `/admin` 是否跳转 `/login`；
   - 管理密码能否登录；
   - 原有配置能否读取；
   - 订阅能否正常更新；
   - 客户端能否正常连接。
7. 新版本稳定后再长期使用；旧部署记录先不要删除，以便回滚。

## 6. 免费额度和可能费用

当前无需充值，Cloudflare 费用为 0。帖子提到的“几块钱一年”主要指可选的自定义域名，而不是 Pages 部署费。

### Workers / Pages Functions 免费额度

- 每个 Cloudflare 账户合计每天 `100,000` 次动态请求；
- 每天 UTC 00:00 重置，即北京时间上午 8:00；
- 免费套餐单次请求 CPU 时间通常上限为 10 ms；
- WebSocket 建立连接算一次 Worker 请求，已建立连接后的每条消息不会分别计作请求。

### KV 免费额度

- 读取：每天 `100,000` 次；
- 写入：每天 `1,000` 次；
- 删除：每天 `1,000` 次；
- 列表查询：每天 `1,000` 次；
- 存储：`1 GB`。

免费套餐超额后不会自动扣费或自动升级，相关请求或操作会暂时失败，等待额度重置即可恢复。

### 如果主动升级

Workers Paid 最低为 **US$5/月/账户**，不是一次性充值。套餐包含更高请求和 KV 额度，超出套餐内额度后还会按量计费。因此没有明确需要时，不建议开通。

官方价格：

- <https://developers.cloudflare.com/workers/platform/pricing/>
- <https://developers.cloudflare.com/kv/platform/pricing/>
- <https://developers.cloudflare.com/pages/functions/pricing/>

## 7. 哪些资源绝对不要随手删除

按重要程度排序：

1. **Cloudflare 账户及其登录恢复方式**：失去账号登录能力，会失去整个项目的管理权。
2. **Pages 项目 `edgetunnel-20260826`**：删除后公开地址、代码和项目配置消失。
3. **KV 命名空间 `EDT2`**：删除后已保存的后台配置可能不可恢复。
4. **生产环境变量 `ADMIN`**：删除或写错会影响管理后台登录。
5. **KV 绑定 `KV → EDT2`**：解绑后程序无法正确读取或保存配置。
6. **本地部署压缩包和本手册**：可用于确认和恢复当前版本。

在执行删除 Pages 项目、删除 KV、重建项目、解绑 KV、修改密码或大版本升级之前，先确认影响，并保留当前部署作为回滚点。

## 8. 建议补做的账户级保护

这些事项不会改变项目运行，但能降低不可逆损失风险：

- 确认 Cloudflare 登录邮箱长期可用；
- 为 Cloudflare 开启双重验证（2FA）；
- 保存 Cloudflare 恢复码到可信的密码管理器或离线安全位置；
- 管理密码保存在密码管理器，不依赖浏览器剪贴板；
- 不与陌生人共享 Cloudflare 账号；
- 如果未来创建 API Token，只授予必要的最小权限；
- 定期在 Cloudflare 控制台检查 Workers 请求量和 KV 用量；
- 如果未来开通付费套餐，设置用量提醒或预算提醒。

## 9. 快速故障排查

### 首页打不开

1. 检查 Pages 项目最新生产部署是否成功。
2. 检查是否达到 Workers 当日免费请求上限。
3. 检查 Cloudflare 服务状态：<https://www.cloudflarestatus.com/>。

### `/admin` 打不开或无法登录

1. 确认地址是 <https://edgetunnel-20260826.pages.dev/admin>。
2. 检查生产环境变量 `ADMIN` 是否存在。
3. 如果忘记密码，替换 `ADMIN` 后重新部署。
4. 不要在聊天或截图中发送密码。

### 后台能打开，但配置无法保存或读取

1. 确认 `EDT2` 命名空间存在。
2. 确认 Pages 的变量名是大写 `KV`。
3. 确认 `KV` 绑定的实际命名空间是 `EDT2`。
4. 检查 KV 当日写入或读取额度是否已用完。

### 修改变量后没有生效

1. 确认修改的是生产环境而不是预览环境。
2. 保存所有未保存的更改。
3. 创建一次新的生产部署。
4. 在无痕窗口或清除相关站点状态后重新验证。

## 10. 已完成的验证记录

2026-08-26 已验证：

- Pages 第一次生产部署成功；
- 创建 `EDT2` KV 命名空间成功；
- KV 绑定 `KV → EDT2` 成功；
- 生产环境变量 `ADMIN` 保存成功；
- 修改变量后完成第二次生产部署；
- 首页外部访问返回 HTTP `200`；
- 未登录访问 `/admin` 返回 HTTP `302` 并跳转 `/login`；
- 使用管理密码实际登录成功；
- 管理后台完整加载；
- 浏览器控制台没有发现报错；
- Cloudflare 账户当时没有已接入域名，因此未配置自定义域名。

---

最后提醒：本文档用于帮助恢复和定位资源，但它本身也包含账户 ID、项目名和内部资源标识。不要公开发布；如果需要发给别人排查问题，请先删除账户 ID、Namespace ID 和所有可能识别项目的信息。
<!-- goodidea:snapshot:end -->

## 关联闪念

_暂无_
