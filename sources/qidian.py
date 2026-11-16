#!/usr/bin/env python3
"""按口味从起点月票榜挑网文（走移动端 m.qidian.com，桌面站有 WAF 拦，移动端直连可抓）。

只读排行榜页，不需要登录；登录态只影响"个性化推荐"，不影响榜单。

用法::

    qidian_pick.py                    # 科幻/悬疑/游戏/历史/军事/轻小说 六榜
    qidian_pick.py --cats 9,10 --limit 8
    qidian_pick.py --json             # 机器可读

口味依据 profile.json：种田/文明推演/冷幽默、系统自洽、
后宫+政治博弈可以，龙傲天降智爽文不行。
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
PROXY = config.PROXY
BASE = "https://m.qidian.com/rank/yuepiao/catid{cat}/{month}/"

CATS = {
    9: "科幻", 10: "悬疑灵异", 7: "游戏", 5: "历史", 6: "军事", 12: "轻小说",
    21: "玄幻", 22: "仙侠",
}

# 作者加成（他明确追/认可的）
AUTHORS = {
    "远瞳": 5, "爱潜水的乌贼": 3, "榴弹怕水": 2, "黑山老鬼": 1, "轻泉流响": 1,
}
# 弃书 / 已读名单来自 profile.json（novels_seen），不重复推荐
DROPPED = {str(x) for x in config.profile_list("novels_seen")}

# 书架种子：已在追的书不重复推荐，同时用来算分类偏好
SHELF_PATH = str(config.state_dir("qidian") / "bookshelf_seed.json")


def load_shelf() -> tuple[set, dict]:
    try:
        data = json.loads(Path(SHELF_PATH).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set(), {}
    titles = {b["title"] for b in data.get("books", [])}
    counts: dict = {}
    for book in data.get("books", []):
        counts[book["category"]] = counts.get(book["category"], 0) + 1
    return titles, counts


SHELF_TITLES, SHELF_CATS = load_shelf()

HITS = {
    "种田": 3, "经营": 3, "领地": 2, "文明": 3, "推演": 3, "工业": 3, "工程": 2,
    "科幻": 2, "星际": 2, "赛博": 2, "机甲": 2, "末世": 1, "灾变": 1,
    "军事": 2, "战争": 2, "历史": 2, "权谋": 3, "政治": 3, "博弈": 3, "庙堂": 2,
    "群像": 2, "家族": 1, "传承": 2, "世代": 2,
    "幽默": 2, "搞笑": 2, "冷幽默": 3, "吐槽": 1,
    "解谜": 2, "规则": 2, "推理": 2, "克苏鲁": 1, "诡异": 1,
    "后宫": 1, "系统": 1, "流水线": 2, "基建": 3, "朝廷": 2,
}
AVOID = {
    "龙傲天": 4, "无敌流": 4, "打脸": 3, "装逼": 3, "签到": 3, "开局送": 3,
    "舔狗": 2, "赘婿": 2, "无敌": 2, "秒杀": 2, "躺平": 1,
    "佣兵": 3, "杀敌": 3, "爆属性": 4, "惩戒军": 3, "成为最强": 2, "反杀": 1,
}


def fetch(cat: int, month: str) -> str:
    url = BASE.format(cat=cat, month=month)
    last: Optional[Exception] = None
    for proxy in (None, PROXY):
        try:
            opener = (urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
                      if proxy else urllib.request.build_opener(urllib.request.ProxyHandler({})))
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            with opener.open(request, timeout=25) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"抓取失败 {url}: {last}")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def parse(html: str, cat_name: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for chunk in re.split(r'<div class="y-list__item"', html)[1:]:
        url = re.search(r'href="//m\.qidian\.com/book/(\d+)/?"', chunk)
        title = re.search(r'title="([^"]+?)最新章节', chunk)
        if not (url and title):
            continue
        text = clean(chunk)
        meta = re.search(r"([^ ·]{2,20}) · ([^ ·]{2,10}) · ([\d.]+万字)", text)
        votes = re.search(r"(?:^|\s)(\d+(?:\.\d+)?万?)月票", text)
        # 简介：去掉序号、书名、月票与尾部 meta
        body = text
        for prefix in (title.group(1),):
            body = body.replace(prefix, " ", 1)
        if votes:
            body = body.replace(votes.group(0), " ")
        if meta:
            body = body.replace(meta.group(0), " ")
        body = re.sub(r"^data-index=\"\d+\">\s*\d+\s*", "", body)
        body = re.sub(r"\s{2,}", " ", body).strip()
        items.append({
            "id": url.group(1),
            "title": html_lib.unescape(title.group(1)),
            "author": meta.group(1) if meta else "",
            "category": meta.group(2) if meta else cat_name,
            "words": meta.group(3) if meta else "",
            "votes": votes.group(1) if votes else "",
            "summary": body[:260],
            "url": f"https://m.qidian.com/book/{url.group(1)}/",
        })
    return items


def score(book: Dict[str, Any]) -> Dict[str, Any]:
    text = f"{book['title']} {book['summary']}"
    reasons: List[str] = []
    total = 0.0
    if book["author"] in AUTHORS:
        total += AUTHORS[book["author"]]
        reasons.append(f"+{AUTHORS[book['author']]} 作者 {book['author']}")
    for word, weight in HITS.items():
        if word in text:
            total += weight
            reasons.append(f"+{weight} {word}")
    for word, weight in AVOID.items():
        if word in text:
            total -= weight
            reasons.append(f"-{weight} {word}")
    fav = SHELF_CATS.get(book.get("category", ""), 0)
    if fav >= 5:
        total += 2
        reasons.append(f"+2 书架偏好分类 {book['category']}({fav}本)")
    elif fav >= 3:
        total += 1
        reasons.append(f"+1 书架偏好分类 {book['category']}({fav}本)")
    return {"score": round(total, 1), "reasons": reasons}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cats", default="9,10,7,5,6,12")
    parser.add_argument("--month", default="202611")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    books: List[Dict[str, Any]] = []
    for cat in [int(c) for c in args.cats.split(",") if c.strip()]:
        try:
            html = fetch(cat, args.month)
        except Exception as exc:  # noqa: BLE001
            print(f"跳过 {cat}: {exc}", file=sys.stderr)
            continue
        books.extend(parse(html, CATS.get(cat, str(cat))))

    seen, unique = set(), []
    for book in books:
        if book["id"] in seen:
            continue
        seen.add(book["id"])
        if book["title"] in DROPPED or book["title"] in SHELF_TITLES:
            continue
        book.update(score(book))
        if book["score"] <= 0:
            continue
        unique.append(book)

    unique.sort(key=lambda b: b["score"], reverse=True)
    picked = unique[: args.limit]
    if args.json:
        print(json.dumps({"picked": picked, "total_candidates": len(books)}, ensure_ascii=False, indent=2))
        return 0
    for book in picked:
        print(f"[{book['score']:>4}] {book['title']}（{book['author']}·{book['category']}·{book['words']}·"
              f"{book['votes']}月票）")
        print(f"       {' | '.join(book['reasons'][:5])}")
        print(f"       {book['summary'][:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
