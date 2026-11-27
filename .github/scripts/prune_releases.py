#!/usr/bin/env python3
"""清理 herdr-cn 过时的 release。

规则：
- 预览版（prerelease）只留最新 1 个
- 当前版本的正式版：带日期的留最近 KEEP_DATED 个，不带日期的留 1 个
- 上一个版本只留 1 个（留作回滚）
- 更老的版本全部删除
不认识 tag 格式的一律不动。
"""
import json
import os
import re
import subprocess
import sys

REPO = os.environ.get("REPO", "yuloop/herdr-cn")
CURRENT_VER = os.environ.get("CURRENT_VER", "")
KEEP_DATED = int(os.environ.get("KEEP_DATED", "5"))
DRY = "--dry-run" in sys.argv or os.environ.get("DRY") == "1"

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)-cn(?:-(\d{8}))?$")


def gh(args):
    r = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def main():
    raw = gh(["api", f"repos/{REPO}/releases?per_page=100", "--paginate"])
    # --paginate 会拼接多页 JSON 对象，逐个解析
    dec = json.JSONDecoder()
    rels, i, s = [], 0, raw.strip()
    while i < len(s):
        while i < len(s) and s[i] in " \n\r\t":
            i += 1
        if i >= len(s):
            break
        obj, j = dec.raw_decode(s, i)
        rels.extend(obj if isinstance(obj, list) else [obj])
        i = j

    cur = CURRENT_VER or max(
        (TAG_RE.match(r["tag_name"]).group(1) + "." + TAG_RE.match(r["tag_name"]).group(2) + "." + TAG_RE.match(r["tag_name"]).group(3)
         for r in rels if TAG_RE.match(r["tag_name"] or "")),
        default="0.0.0", key=vkey)

    previews, stable = [], []
    for r in rels:
        t = r.get("tag_name") or ""
        (previews if r.get("prerelease") else stable).append((t, r))

    keep, drop = [], []

    # 1) 预览版只留最新 1 个（nightly workflow 也会清，这里兜底）
    for idx, item in enumerate(previews):
        (keep if idx == 0 else drop).append(item)

    # 2) 正式版按版本分组
    by_ver = {}
    for t, r in stable:
        m = TAG_RE.match(t)
        if not m:
            keep.append((t, r))  # 不认识的 tag 一律不动
            continue
        ver = ".".join(m.group(1, 2, 3))
        by_ver.setdefault(ver, []).append((t, r, m.group(4)))

    others = sorted([v for v in by_ver if v != cur and vkey(v) < vkey(cur)], key=vkey)
    prev = others[-1] if others else None

    for ver, items in by_ver.items():
        items.sort(key=lambda x: (x[2] or "00000000"), reverse=True)  # 日期新的在前
        if ver == cur:
            dated = [x for x in items if x[2]]
            undated = [x for x in items if not x[2]]
            keep.extend((t, r) for t, r, _ in dated[:KEEP_DATED])
            drop.extend((t, r) for t, r, _ in dated[KEEP_DATED:])
            keep.extend((t, r) for t, r, _ in undated[:1])
            drop.extend((t, r) for t, r, _ in undated[1:])
        elif ver == prev:
            keep.append((items[0][0], items[0][1]))
            drop.extend((t, r) for t, r, _ in items[1:])
        else:
            drop.extend((t, r) for t, r, _ in items)

    print(f"当前版本: {cur} / 保留的上一个版本: {prev or '-'}")
    print(f"保留 {len(keep)} 条:")
    for t, _ in keep:
        print("  keep", t)
    print(f"删除 {len(drop)} 条:")
    for t, r in drop:
        print("  drop", t, r["id"])
        if not DRY:
            try:
                gh(["api", "-X", "DELETE", f"repos/{REPO}/releases/{r['id']}"])
            except Exception as e:  # noqa: BLE001
                print("   delete failed:", e)
    if DRY:
        print("(dry-run，未真正删除)")


if __name__ == "__main__":
    main()