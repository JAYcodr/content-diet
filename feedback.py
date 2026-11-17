#!/usr/bin/env python3
"""把「这个不要 / 这个看过了」写进 feedback.json —— 片单卡片的反馈入口。

用法::

    python3 feedback.py skip 3            # 最近一期第 3 条：别再推
    python3 feedback.py seen 1,2          # 第 1、2 条：看过了
    python3 feedback.py skip --name 碧蓝之海
    python3 feedback.py list              # 看当前 feedback.json
    python3 feedback.py list --period     # 最近一期卡片的序号清单

序号来自最近一次发出去的周卡（`state/last_weekly.json`，发卡时写入）。
写进 feedback.json 的名字会同时进筛选排除集（`config.feedback_excludes`），
下次抓取时直接跳过——这是这套系统里唯一会持续改变结果的输入。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import config  # noqa: E402

ACTIONS = {"skip": "skip", "seen": "seen"}


def last_weekly() -> dict:
    path = config.state_dir("", quiet=True) / "last_weekly.json"
    if not path.exists():
        raise SystemExit("找不到 last_weekly.json —— 还没发过周卡，或者状态目录不对")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(args) -> list[tuple[str, str]]:
    """→ [(category, title)]"""
    data = last_weekly()
    items = data.get("items") or []
    picked: list[tuple[str, str]] = []

    if args.names:
        wanted = [n.strip() for n in args.names if n.strip()]
        for w in wanted:
            hit = [it for it in items if w in it["title"] or it["title"] in w]
            if not hit:
                raise SystemExit(f"最近一期里没有「{w}」。用 list --period 看当期有哪些。")
            picked.append((hit[0]["kind"], hit[0]["title"]))
        return picked

    if not args.numbers:
        raise SystemExit("给序号或 --name，例如：feedback.py skip 3")
    for token in args.numbers:
        for part in token.replace("，", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit():
                raise SystemExit(f"序号必须是数字：{part}")
            hit = [it for it in items if it["n"] == int(part)]
            if not hit:
                raise SystemExit(f"最近一期没有第 {part} 条（共 {len(items)} 条）")
            picked.append((hit[0]["kind"], hit[0]["title"]))
    return picked


def apply(action: str, picks: list[tuple[str, str]]) -> None:
    data = config.load_feedback()
    changed = []
    for category, title in picks:
        bucket = data.setdefault(category, {})
        lst = bucket.setdefault(ACTIONS[action], [])
        if title in lst:
            print(f"跳过（已在 {category}.{action}）：{title}", file=sys.stderr)
            continue
        lst.append(title)
        # 同一部不能既 seen 又 skip：换边时把旧记录摘掉
        other = bucket.setdefault("seen" if action == "skip" else "skip", [])
        if title in other:
            other.remove(title)
        changed.append((category, title))
    if changed:
        path = config.save_feedback(data)
        for c, t in changed:
            print(f"✓ {c}.{action}：{t}")
        print(f"写入 {path}")
    else:
        print("没有新的写入。")


def show(period_only: bool) -> None:
    if period_only:
        data = last_weekly()
        print(f"期次 {data.get('period')}，共 {len(data.get('items') or [])} 条：")
        for it in data.get("items") or []:
            print(f"  {it['n']}. [{it['kind']}] {it['title']}")
        return
    data = config.load_feedback()
    if not data:
        print("feedback.json 还是空的。")
        return
    for category, buckets in data.items():
        parts = [f"{k}: {len(v)}" for k, v in buckets.items() if v]
        print(f"{category}: {'  '.join(parts) if parts else '(空)'}")
        for k in ("skip", "seen"):
            for t in buckets.get(k) or []:
                print(f"  - [{k}] {t}")


def main() -> int:
    ap = argparse.ArgumentParser(description="周卡反馈：skip / seen 写进 feedback.json")
    ap.add_argument("action", nargs="?", choices=["skip", "seen", "list"], help="skip / seen / list")
    ap.add_argument("numbers", nargs="*", help="序号，可逗号分隔：3 或 1,2")
    ap.add_argument("--name", dest="names", action="append", default=[], help="按名字，可重复")
    ap.add_argument("--period", action="store_true", help="list 时看最近一期的序号清单")
    args = ap.parse_args()

    if args.action in (None, "list"):
        show(args.period)
        return 0

    apply(args.action, resolve(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
