# 远程 vs 本地：零下载的状态比对与推送验证

对象在代理上拖不动（几百 KB/s 以下、动辄卡死）时，**不要**为了回答「远程是不是最新的」去 fetch。需要的其实只有两样东西：提交拓扑和文件清单——两样都能用 GitHub API 拿，再在本地算哈希。

## 0. 先看清拓扑

```bash
cd ~/Documents/Goodidea
git config --get-all remote.origin.fetch   # 这个 clone 通常只配 +refs/heads/v0.16:...
git ls-remote --heads origin               # 远程全部分支及 tip sha（<1s）
git rev-parse --short HEAD origin/<本地跟踪的分支>
```

refspec 窄 ⇒ 本地没有其他分支的 remote-tracking ref（`git branch -a` 看不到 `origin/main`），但 `git ls-remote` 照样能拿到它们的 sha。**不要为了看 main 去改 refspec 或 fetch**。

## 1. 提交层面差异（ahead/behind/提交与文件清单）

```bash
export HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897
gh api "repos/ydds123/good-idea/compare/<base>...<head>" > /tmp/cmp.json
```

`/tmp/cmp.json` 里有 `status`（ahead / behind / diverged）、`ahead_by`、`behind_by`、`merge_base_commit.sha`、完整的 `commits[]`、以及 `files[]`。

- `status=ahead` ＋ `merge_base == base 的 tip` ⇒ base 是 head 的纯祖先：base 没有任何 head 缺少的东西，可直接快进。
- `files[]` 上限 300 条、超限的条目统计会退化成 `+0 -0`，看文件**数量**别只看这一栏。
- 反方向再比一次（`<head>...<base>`）可交叉验证 ahead/behind 的归属。

## 2. 文件层面差异（远程整棵树 vs 本地目录）

```bash
gh api "repos/ydds123/good-idea/git/trees/<ref>?recursive=1" > /tmp/tree.json
python3 <本 skill 目录>/scripts/remote-tree-diff.py /tmp/tree.json ~/Documents/Goodidea
```

脚本按 git 的 blob 规则算本地哈希（`sha1("blob <字节数>\0" + 内容)`）与 API 给的 blob sha 对比，输出四类：一致 / 内容不同 / 远程有本地无 / 本地有远程无；有差异时退出码 1。

**坑**：不要用 `git hash-object --stdin-paths` 做批量比对——只要清单里混进一个不存在的路径，它整体 `fatal` 退出、stdout 为空，逐行 zip 后会得到「只缺 1 个文件」这种假结论。本地哈希自己算，或先过滤出真实存在的路径。

**坑**：`git config http.proxy` 只对 git 生效，gh/curl 不读它——调 API 必须显式给 `HTTPS_PROXY/HTTP_PROXY=http://127.0.0.1:7897`。裸 curl 打 `api.github.com` 未认证，从共享代理出口 IP 出站常吃 `403 API rate limit exceeded`；用已认证的 `gh api`（5000/h）就没事。

## 3. 推送后的回读验证（write → read-back）

```bash
git add -A && git commit -m "chore: 同步本地工作区状态（<一句话>）"
git push origin <分支>
git ls-remote origin refs/heads/<分支>        # 应为新 sha
gh api "repos/ydds123/good-idea/git/trees/<分支>?recursive=1" > /tmp/tree.json
python3 <本 skill 目录>/scripts/remote-tree-diff.py /tmp/tree.json ~/Documents/Goodidea
# 四类全为 0（一致数=两边文件数）才算推送完成
```

## 仓库拓扑（稳态事实）

- 远程 `ydds123/good-idea` 常年两条线：`main`（开发主线，含 `src/`、`tests/`、`.agents/skills/goodidea-*`、方案与卡片空间）与 `v0.16`（与本地工作区一一对应的工作线）。
- `v0.16` 往往是 `main` 的祖先：本地「同步到最新」不等于「仓库最新」——先把这两个问题分开回答，别混成一句。
- 本地工作区里 `文档/临时/*` 之类的文件可能是「未 tracked 但 main 上已有」的状态；比对时用第 2 步的树比对，别靠 `git status` 推断远程有没有。
