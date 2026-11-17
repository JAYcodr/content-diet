#!/usr/bin/env python3
"""把「已看 / 不想看」回写到档案旁边，下次筛选直接排掉。

为什么不写回 ``profile.json``：档案是「访谈时他说的」，属于输入；这里是「用了以后
他判的」，属于结果。混在一起会让人分不清哪条是口味、哪条是已消费记录，而且重跑
``setup/init.py`` 会把反馈冲掉。所以单独放 ``feedback.json``，卡片筛选两边都读。

用法::

    python3 setup/mark.py seen anime 葬送的芙莉莲 孤独摇滚   # 看过了，别再推
    python3 setup/mark.py skip novel 玄鉴仙族              # 不想看
    python3 setup/mark.py seen album "Aimer - Open α Door"  # 专辑：艺人 - 专辑名
    python3 setup/mark.py seen game "薩爾達傳說 王國之淚"
    python3 setup/mark.py unmark seen anime 孤独摇滚        # 手滑了
    python3 setup/mark.py list                            # 看现在记了什么

回写落在 ``$CONTENT_DIET_HOME/feedback.json``；状态目录不可写时会给你一句可照做的提示。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402

CATEGORIES = {
    "anime": "番剧",
    "novel": "网文",
    "album": "专辑",
    "game": "游戏",
}
KINDS = {"seen": "已看", "skip": "不想看"}


def load() -> dict:
    data = config.load_feedback()
    for category in CATEGORIES:
        bucket = data.get(category)
        if not isinstance(bucket, dict):
            bucket = {}
            data[category] = bucket
        for kind in KINDS:
            if not isinstance(bucket.get(kind), list):
                bucket[kind] = []
    return data


def save(data: dict) -> Path:
    data.pop("_comment", None)
    data["_comment"] = ("由 setup/mark.py 维护：卡片筛选时与 profile.json 合并排重。"
                        "改档案（init.py）不会清掉这里。")
    return config.save_feedback(data)


def add(category: str, kind: str, titles: list) -> int:
    data = load()
    entries = data[category][kind]
    added = 0
    for title in titles:
        title = title.strip()
        if title and title not in entries:
            entries.append(title)
            added += 1
    save(data)
    print(f"已记入 {KINDS[kind]}·{CATEGORIES[category]}：{added} 条（共 {len(entries)} 条）→ {config.feedback_path()}")
    return 0


def remove(category: str, kind: str, titles: list) -> int:
    data = load()
    entries = data[category][kind]
    removed = []
    for title in titles:
        title = title.strip()
        if title in entries:
            entries.remove(title)
            removed.append(title)
    save(data)
    print(f"已移除 {len(removed)} 条；{CATEGORIES[category]}·{KINDS[kind]} 还剩 {len(entries)} 条")
    return 0


def show() -> int:
    data = config.load_feedback()
    if not data:
        print(f"还没有回写记录（{config.feedback_path()} 不存在）")
        return 0
    for category, label in CATEGORIES.items():
        bucket = data.get(category) or {}
        for kind, kind_label in KINDS.items():
            entries = bucket.get(kind) or []
            if entries:
                print(f"{label}·{kind_label}（{len(entries)}）：" + "、".join(entries))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="回写「已看 / 不想看」，参与下一轮排重")
    parser.add_argument("action", choices=["seen", "skip", "unmark", "list"])
    parser.add_argument("category", nargs="?", choices=list(CATEGORIES), help="anime / novel / album / game")
    parser.add_argument("titles", nargs="*", help="作品名（专辑用「艺人 - 专辑名」）")
    parser.add_argument("--kind", choices=list(KINDS), help="unmark 时指定要撤掉哪一类")
    args = parser.parse_args()

    if args.action == "list":
        return show()
    if not args.category or not args.titles:
        parser.error("需要分类和至少一个作品名，例如：mark.py seen anime 葬送的芙莉莲")

    if args.action == "unmark":
        kinds = [args.kind] if args.kind else list(KINDS)
        rc = 0
        for kind in kinds:
            rc |= remove(args.category, kind, args.titles)
        return rc
    return add(args.category, args.action, args.titles)


if __name__ == "__main__":
    sys.exit(main())
