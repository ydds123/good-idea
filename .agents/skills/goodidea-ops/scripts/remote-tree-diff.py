#!/usr/bin/env python3
"""比对远程 git 树与本地目录，零对象下载。

用法:
    gh api "repos/<owner>/<repo>/git/trees/<ref>?recursive=1" > /tmp/tree.json
    python3 remote-tree-diff.py /tmp/tree.json [本地目录，默认 .]

原理: git 对普通文件的哈希 = sha1(b"blob <字节数>\\0" + 内容)，本地直接算就能和
GitHub API 给的 blob sha 对比，全程不 fetch 任何对象。

输出: 一致 / 内容不同 / 远程有本地无 / 本地有远程无 四类计数与清单（每类最多列 40 条）。
退出码: 0 = 两边完全一致，1 = 有差异，2 = 用法错误。
"""
import hashlib
import json
import os
import sys

MAX_LIST = 40


def blob_sha(path):
    with open(path, 'rb') as f:
        data = f.read()
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    tree_path = sys.argv[1]
    root = sys.argv[2] if len(sys.argv) > 2 else '.'

    with open(tree_path) as f:
        tree = json.load(f)
    entries = tree.get('tree', [])
    blobs = {e['path']: e['sha'] for e in entries if e.get('type') == 'blob'}
    if not blobs:
        print('警告: 树里没有 blob 条目——ref 写错，或 API 响应被截断(truncated=%s)' % tree.get('truncated'),
              file=sys.stderr)
        return 2

    local = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != '.git']
        for fn in filenames:
            local.add(os.path.relpath(os.path.join(dirpath, fn), root))

    same, different = [], []
    for path, sha in blobs.items():
        if path not in local:
            continue
        full = os.path.join(root, path)
        if not os.path.isfile(full):
            continue
        (same if blob_sha(full) == sha else different).append(path)

    remote_only = sorted(set(blobs) - local)
    local_only = sorted(local - set(blobs))

    print('远程 %s 文件数 %d | 本地文件数 %d' % (str(tree.get('sha', '?'))[:7], len(blobs), len(local)))
    print('一致 %d | 内容不同 %d | 远程有本地无 %d | 本地有远程无 %d'
          % (len(same), len(different), len(remote_only), len(local_only)))

    for title, items in (('内容不同', sorted(different)),
                         ('远程有本地无', remote_only),
                         ('本地有远程无', local_only)):
        if not items:
            continue
        print('\n[%s]' % title)
        for path in items[:MAX_LIST]:
            print('  ', path)
        if len(items) > MAX_LIST:
            print('   ...共 %d' % len(items))

    return 0 if not (different or remote_only or local_only) else 1


if __name__ == '__main__':
    sys.exit(main())
