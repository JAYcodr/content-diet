#!/usr/bin/env python3
"""每周一张片单卡：番剧（Bangumi 当季）+ 网文（起点月票榜），带封面发飞书。

用法::

    weekly_card.py --preview          # 只打印卡片 JSON
    weekly_card.py                    # 组卡并发送到飞书 home channel
    weekly_card.py --anime 4 --novel 4 --chat oc_xxx

数据源都是公开页面/接口，不需要任何登录：
  * 番剧：Bangumi 搜索接口（token 只用于提高限额与读收藏）
  * 网文：m.qidian.com 月票榜（桌面站有 WAF，移动端直连）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


_ROOT = Path(__file__).resolve().parent.parent      # 直接 python3 <script> 也能 import core
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import config, sent  # noqa: E402
from core.feishu import card_v2, cols, footer, img, md, send_card, upload_image  # noqa: E402

from sources import bangumi as anime_pick  # noqa: E402
from sources import qidian as qidian_pick  # noqa: E402

DEFAULT_CHAT = ""  # 运行时从 FEISHU_CHAT_ID 读
CACHE = config.state_dir("covers")
KEY_CACHE = config.state_dir("feishu") / "img_keys.json"
PROXY = config.PROXY
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
CST = timezone(timedelta(hours=8))

_REPORTED: set = set()


def report_once(key: str, message: str) -> None:
    """降级提示只打一次：每张封面都刷一行等于没有提示。"""
    if key in _REPORTED:
        return
    _REPORTED.add(key)
    print(message, file=sys.stderr)


def fetch_image(url: str, name: str, *, via_proxy: bool) -> Optional[Path]:
    """下载封面到缓存，返回本地路径。Bangumi 图站直连不通，必须走代理。"""
    if not url:
        return None
    if not config.try_mkdir(CACHE):
        report_once("cover-cache",
                    "封面缓存目录不可用（状态目录不可写）：本次每张封面都会重新下载并重传，"
                    "卡片仍会出，只是慢")
        return None          # 只读环境：没有封面缓存就降级成纯文字行
    target = CACHE / f"{name}.jpg"
    if target.exists() and target.stat().st_size > 1000:
        return target
    proxies = [(None, PROXY)] if via_proxy else [(None, None), (PROXY, PROXY)]
    for _, proxy in proxies:
        try:
            opener = (urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
                      if proxy else urllib.request.build_opener(urllib.request.ProxyHandler({})))
            request = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Referer": "https://bookcover.yuewen.com/" if not via_proxy else "https://bgm.tv/"})
            with opener.open(request, timeout=25) as resp:
                data = resp.read()
            if len(data) > 1000:
                target.write_bytes(data)
                return target
        except Exception:  # noqa: BLE001
            continue
    return None


def img_key_for(path: Optional[Path]) -> Optional[str]:
    if not path:
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    cache: Dict[str, str] = {}
    if KEY_CACHE.exists():
        try:
            cache = json.loads(KEY_CACHE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cache = {}
    if digest in cache:
        return cache[digest]
    try:
        key = upload_image(str(path))
    except Exception as exc:  # noqa: BLE001
        print(f"封面上传失败 {path.name}: {exc}", file=sys.stderr)
        return None
    cache[digest] = key
    if not config.try_mkdir(KEY_CACHE.parent):
        return key
    KEY_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return key


def anime_rows(limit: int) -> List[Dict[str, Any]]:
    payload = anime_pick.collect("airing", None, limit)
    rows = []
    for item in payload["picked"][:limit]:
        cover = fetch_image(item["image"], f"bgm_{item['id']}", via_proxy=True)
        reason = "、".join(r.split(" ", 1)[-1] for r in item["reasons"][:3])
        rows.append({"title": item["name"], "sub": f"Bangumi {item['bgm_score']}",
                     "note": reason, "cover": cover, "url": item["url"]})
    return rows


def novel_category_ids() -> List[int]:
    """档案 ``novel_categories``（中文分类名）→ 起点榜单 catid。

    空 = 用默认六榜；名字对不上时明确提示并回落，不静默。
    """
    default = [9, 10, 7, 5, 6, 12]
    preferred = [str(x).strip() for x in config.profile_list("novel_categories") if str(x).strip()]
    if not preferred:
        return default
    by_name = {name: cid for cid, name in qidian_pick.CATS.items()}
    ids: List[int] = []
    for name in preferred:
        cid = by_name.get(name)
        if cid is None:                      # 「悬疑」对「悬疑灵异」这种近似名也算命中
            cid = next((c for n, c in by_name.items() if name in n or n in name), None)
        if cid is not None and cid not in ids:
            ids.append(cid)
    if not ids:
        print(f"档案里的分类 {preferred} 对不上起点榜单分类 {sorted(by_name)}，回落到默认六榜",
              file=sys.stderr)
        return default
    return ids


def novel_rows(limit: int) -> List[Dict[str, Any]]:
    html_items: List[Dict[str, Any]] = []
    for cat in novel_category_ids():
        try:
            html = qidian_pick.fetch(cat, datetime.now(CST).strftime("%Y%m"))
        except Exception as exc:  # noqa: BLE001
            print(f"跳过 {cat}: {exc}", file=sys.stderr)
            continue
        html_items.extend(qidian_pick.parse(html, qidian_pick.CATS.get(cat, str(cat))))
    scored = []
    dropped = qidian_pick.dropped()
    for book in html_items:
        if book["title"] in dropped or book["title"] in qidian_pick.SHELF_TITLES:
            continue
        book.update(qidian_pick.score(book))
        scored.append(book)
    scored.sort(key=lambda b: b["score"], reverse=True)

    # 分类轮转，避免一整张卡全是科幻
    picked, per_cat, cap = [], {}, 2
    for book in scored:
        cat = book.get("category", "")
        if per_cat.get(cat, 0) >= cap or (cat, book["id"]) in {(b["category"], b["id"]) for b in picked}:
            continue
        picked.append(book)
        per_cat[cat] = per_cat.get(cat, 0) + 1
        if len(picked) >= limit:
            break
    rows = []
    for book in picked:
        cover = fetch_image(f"https://bookcover.yuewen.com/qdbimg/349573/{book['id']}/180",
                            f"qd_{book['id']}", via_proxy=False)
        reason = "、".join(r.split(" ", 1)[-1] for r in book["reasons"][:3]) or "榜单高位"
        rows.append({"title": book["title"],
                     "sub": f"{book['author']} · {book['category']} · {book['words']}",
                     "note": f"{reason}｜{book['votes']}月票", "cover": cover, "url": book["url"]})
    return rows


def card_title() -> str:
    """标题里的称呼来自档案；没填就是中性标题——绝不硬编码某个人的名字。"""
    name = config.display_name()
    return f"{name} · 本周片单" if name else "本周片单"


def build_card(anime: List[Dict[str, Any]], novels: List[Dict[str, Any]]) -> Dict[str, Any]:
    today = datetime.now(CST)
    n = 0
    elements: List[Dict[str, Any]] = [md(f"**📺 番剧 · 当季**　<font color='grey'>Bangumi 评分 + 口味匹配</font>")]
    for row in anime:
        n += 1
        key = img_key_for(row["cover"])
        body = f"**{n}. {row['title']}**\n<font color='grey'>{row['sub']}</font>\n{row['note']}　[条目]({row['url']})"
        elements.append(cols((1, [img(key, size="96px 136px", radius="6px")]), (3, [md(body)]))
                        if key else md(body))
        elements.append({"tag": "hr"})

    elements.append(md("**📖 网文 · 月票榜**　<font color='grey'>起点移动端榜单</font>"))
    for row in novels:
        n += 1
        key = img_key_for(row["cover"])
        body = f"**{n}. {row['title']}**\n<font color='grey'>{row['sub']}</font>\n{row['note']}　[书页]({row['url']})"
        elements.append(cols((1, [img(key, size="96px 136px", radius="6px")]), (3, [md(body)]))
                        if key else md(body))
        elements.append({"tag": "hr"})

    elements.append(md("<font color='grey'>回「3 跳过」或「2 看过了」，下期不再推这部。</font>"))
    elements.append(footer(f"{today.month} 月 {today.day} 日 · 每週日更新 · 數據源 Bangumi / 起點月票榜"))
    return card_v2(title=card_title(), subtitle=f"番剧 {len(anime)} 部 · 网文 {len(novels)} 本",
                   template="turquoise", elements=elements)


def text_summary(anime: List[Dict[str, Any]], novels: List[Dict[str, Any]]) -> str:
    lines = [f"📺 {r['title']}（{r['sub']}）" for r in anime]
    lines += [f"📖 {r['title']}（{r['sub']}）" for r in novels]
    return "\n".join(lines)


def save_last(anime: List[Dict[str, Any]], novels: List[Dict[str, Any]]) -> None:
    """存下这一期的序号 → 条目，供 feedback.py 按「第 3 条」反查。"""
    items, n = [], 0
    for kind, rows in (("anime", anime), ("novel", novels)):
        for r in rows:
            n += 1
            items.append({"n": n, "kind": kind, "title": r["title"], "url": r["url"]})
    path = config.state_dir("") / "last_weekly.json"
    try:
        path.write_text(json.dumps(
            {"period": sent.week_key("weekly"), "items": items}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError as exc:            # 写不下不影响发卡，但要说一声
        print(f"last_weekly 写入失败：{exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anime", type=int, default=4)
    parser.add_argument("--novel", type=int, default=4)
    parser.add_argument("--chat", default=None)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--no-send", action="store_true")
    parser.add_argument("--force-send", action="store_true", help="忽略本周期同内容去重")
    args = parser.parse_args()

    args.chat = args.chat or config.feishu_chat()
    if not args.preview and not args.no_send and not args.chat:
        raise SystemExit("缺少 FEISHU_CHAT_ID")
    anime = anime_rows(args.anime)
    novels = novel_rows(args.novel)
    if not anime and not novels:
        print("两边都没数据，跳过")
        return 2
    card = build_card(anime, novels)
    if args.preview:
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return 0
    print(text_summary(anime, novels))
    if args.no_send:
        return 0
    key = sent.week_key("weekly")
    digest = sent.fingerprint([r["title"] for r in anime], [r["title"] for r in novels],
                              [r["sub"] for r in anime] + [r["sub"] for r in novels])
    if not args.force_send:
        previous = sent.already_sent(key, digest)
        if previous:
            print(f"本周这份片单已经发过（{previous}），跳过；要重发加 --force-send", file=sys.stderr)
            return 0
    try:
        result = send_card(args.chat, card)
        print(f"卡片已发送 {result.get('message_id')}", file=sys.stderr)
        sent.mark_sent(key, digest, str(result.get("message_id")))
        save_last(anime, novels)
    except Exception as exc:  # noqa: BLE001
        print(f"发送失败: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
