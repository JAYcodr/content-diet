#!/usr/bin/env python3
"""把筛选后的任天堂香港新作发成飞书卡片（Card JSON 2.0）。

输入 JSON（stdin 或 --data 文件）::

    {"games": [{"title": "...", "publisher": "...", "date": "2026.11.20",
                "label": "下載版", "url": "https://ec.nintendo.com/...",
                "poster_file": "<state>/nintendo/posters/xxx.jpg",
                "blurb": "一句话说明（可省）"}],
     "skipped": 45,
     "window_days": 45}

用法::

    python3 nintendo_card.py --data games.json --chat oc_xxx
    python3 nintendo_card.py --data games.json --preview   # 只打印卡片 JSON，不发

海报走飞书图片上传，按文件 sha 缓存 img_key，同一张不重复上传。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from core.feishu import card_v2, cols, footer, img, md, send_card, upload_image  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent      # 直接 python3 <script> 也能 import core
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import config, sent  # noqa: E402  # noqa: E402
KEY_CACHE = config.state_dir("feishu") / "img_keys.json"
DEFAULT_CHAT = ""  # 运行时从 FEISHU_CHAT_ID 读


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def img_key(path: Path) -> str | None:
    """上传海报并缓存 img_key；换图（sha 变）会自动重传。"""
    try:
        digest = _sha(path)
    except OSError:
        return None
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
        print(f"海报上传失败 {path.name}: {exc}", file=sys.stderr)
        return None
    cache[digest] = key
    if not config.try_mkdir(KEY_CACHE.parent):
        return key
    KEY_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return key


def short_date(raw: str) -> str:
    parts = (raw or "").split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{int(parts[1])}/{int(parts[2])}"
    return raw or "日期未定"


def build_card(payload: Dict[str, Any]) -> Dict[str, Any]:
    games: Any = payload.get("games")
    if games is None:                      # 旧键 items（nintendo_hk 两个都写，这里也两个都读）
        games = payload.get("items") or []
    games = list(games)
    elements: List[Dict[str, Any]] = []
    order = {"hit": 0, "neutral": 1, "caution": 2}
    games = sorted(games, key=lambda g: (order.get(g.get("taste"), 1), g.get("date") or ""))
    for index, game in enumerate(games):
        star = "★ " if game.get("taste") == "hit" else ""
        text_lines = [f"**{star}{game['title']}**",
                      f"<font color='grey'>{game.get('publisher','')} · {short_date(game.get('date',''))}"
                      f"{' · ' + game['label'] if game.get('label') else ''}</font>"]
        if game.get("taste_note"):
            text_lines.append(f"<text_tag>{game['taste_note']}</text_tag>")
        if game.get("blurb"):
            text_lines.append(game["blurb"])
        if game.get("url"):
            text_lines.append(f"[商店頁]({game['url']})")
        right = [md("\n".join(text_lines))]
        poster = game.get("poster_file")
        key = img_key(Path(poster)) if poster else None
        block = cols((1, [img(key, alt=game["title"], size="150px 84px", radius="6px")]),
                     (3, right)) if key else md("\n".join(text_lines))
        elements.append(block)
        if index != len(games) - 1:
            elements.append({"tag": "hr"})

    skipped = int(payload.get("skipped") or 0)
    window = payload.get("window_days") or 45
    note = f"未來 {window} 天內 · 共 {len(games)} 款（★=口味命中）"
    if skipped:
        note += f" · 另有 {skipped} 款小作/資產翻新未列出"
    elements.append(footer(f"{note} · 資料源 nintendo.com/hk/schedule"))
    return card_v2(title="任天堂香港 · 新作", subtitle=note, template="turquoise",
                   elements=elements)


def text_summary(payload: Dict[str, Any]) -> str:
    items = payload.get("games")
    if items is None:
        items = payload.get("items") or []
    lines = []
    for game in items:
        lines.append(f"🎮 {game['title']}（{game.get('publisher','')}·{short_date(game.get('date',''))}）")
    return "\n".join(lines) or "本周没有值得推的新作"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", help="输入 JSON 文件，缺省读 stdin")
    parser.add_argument("--chat", default=None)
    parser.add_argument("--preview", action="store_true", help="只打印卡片 JSON")
    parser.add_argument("--no-send", action="store_true", help="组卡但不发送")
    parser.add_argument("--force-send", action="store_true", help="忽略同内容去重，强制再发一次")
    args = parser.parse_args()

    raw = Path(args.data).read_text(encoding="utf-8") if args.data else sys.stdin.read()
    args.chat = args.chat or config.feishu_chat()
    payload = json.loads(raw)
    card = build_card(payload)
    if args.preview:
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return 0
    print(text_summary(payload))
    if args.no_send:
        return 0
    ids = sorted(payload_ids(payload))
    key = "games-" + hashlib.sha256(",".join(ids).encode()).hexdigest()[:12]
    digest = sent.fingerprint(card)
    if not args.force_send:
        previous = sent.already_sent(key, digest)
        if previous:
            print(f"这份内容已经发过（{previous}），跳过；要重发加 --force-send", file=sys.stderr)
            return 0
    try:
        result = send_card(args.chat, card)
        print(f"卡片已发送 {result.get('message_id')}", file=sys.stderr)
        sent.mark_sent(key, digest, str(result.get("message_id")))
    except Exception as exc:  # noqa: BLE001
        print(f"卡片发送失败: {exc}", file=sys.stderr)
        return 3
    return 0


def payload_ids(payload: Dict[str, Any]) -> List[str]:
    items = payload.get("games")
    if items is None:
        items = payload.get("items") or []
    return [str(g["id"]) for g in items if isinstance(g, dict) and g.get("id")]


if __name__ == "__main__":
    sys.exit(main())
