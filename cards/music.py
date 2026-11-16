#!/usr/bin/env python3
"""内核层歌手的新发行月报（带专辑封面）→ 飞书卡片。

口径来自 taste_profile 第九章：只推**内核层**（Aimer / 米津 / ヨルシカ / あたらよ / ヒグチアイ …），
**陪伴型（周杰伦、林俊杰、邓紫棋…）绝不推**；给**专辑/完整作品**，不给单曲。

用法::

    music_card.py --days 365 --no-send     # 首次跑：看近一年
    music_card.py --days 45                # 月报：只看最近 45 天
    music_card.py --days 45 --preview      # 只打印卡片 JSON

数据源：网易云音乐公开接口（艺人专辑列表 + 封面 CDN），不需要登录。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config
from core.feishu import card_v2, cols, footer, img, md, send_card, upload_image  # noqa: E402

DEFAULT_CHAT = ""  # 运行时从 FEISHU_CHAT_ID 读
CACHE = config.state_dir("music")
ARTIST_CACHE = CACHE / "artists.json"
KEY_CACHE = config.state_dir("feishu") / "img_keys.json"
# 预置 id（2026-11 实查）：避免首次运行烧掉 12 次搜索触发网易云限流
KNOWN_ARTIST_IDS = {
    "Aimer": 16152, "米津玄師": 159300, "ヨルシカ": 12390232, "あたらよ": 37687426,
    "ヒグチアイ": 942124, "EGOIST": 19353, "やなぎなぎ": 18303, "eill": 30109434,
    "DAOKO": 855508, "宇多田ヒカル": 18122, "りりあ。": 37457784, "こはならむ": 47923697,
}

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
HDRS = {"Referer": "https://music.163.com/", "Cookie": "os=pc; appver=2.9.7", "User-Agent": UA}

# 内核层（taste_profile 第九章）。陪伴型故意不在这里；profile.json 的 core_artists 可以覆盖。
CORE_ARTISTS = None
CORE_ARTISTS_DEFAULT = [
    "Aimer", "米津玄師", "ヨルシカ", "あたらよ", "ヒグチアイ", "EGOIST",
    "やなぎなぎ", "eill", "DAOKO", "宇多田ヒカル", "りりあ。", "こはならむ",
]
# 搜不到时换的查询词（网易云对某些艺人只认其中一种写法）
ARTIST_ALIAS = {"りりあ。": "りりあ", "こはならむ": "Kohana Lam"}
MIN_TRACKS = 3   # 少于 3 轨的当单曲/EP 处理，不算"完整作品"


def api(url: str, *, retries: int = 3) -> Dict[str, Any]:
    """网易云会 406 限流（操作频繁）：退避重试，仍失败就返回空结构。"""
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(request, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            if data.get("code") == 406:
                time.sleep(8 * (attempt + 1))
                continue
            return data
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                print(f"接口失败 {url[:60]}: {exc}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    return {}


def load_artist_cache() -> Dict[str, int]:
    if ARTIST_CACHE.exists():
        try:
            return json.loads(ARTIST_CACHE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def resolve_artist(name: str, cache: Dict[str, int]) -> Optional[int]:
    if name in cache:
        return cache[name]
    if name in KNOWN_ARTIST_IDS:          # 预置表，省一次搜索
        cache[name] = KNOWN_ARTIST_IDS[name]
        return cache[name]
    for query in (name, ARTIST_ALIAS.get(name)):
        if not query:
            continue
        data = api("https://music.163.com/api/search/get/web?s=%s&type=100&limit=1"
                   % urllib.parse.quote(query))
        artists = (data.get("result") or {}).get("artists") or []
        if artists:
            break
        time.sleep(1.2)
    if not artists:
        return None
    cache[name] = artists[0]["id"]
    time.sleep(2.5)
    return cache[name]


def albums(artist_id: int, days: int, today: dt.date) -> List[Dict[str, Any]]:
    data = api(f"https://music.163.com/api/artist/albums/{artist_id}?limit=40")
    out = []
    for item in data.get("hotAlbums") or []:
        published = item.get("publishTime")
        if not published:
            continue
        when = dt.datetime.fromtimestamp(published / 1000).date()
        if (today - when).days > days:
            continue
        if int(item.get("size") or 0) < MIN_TRACKS:
            continue
        out.append({
            "id": item["id"],
            "name": item["name"],
            "cover_url": item.get("picUrl") or "",
            "date": when.isoformat(),
            "tracks": int(item.get("size") or 0),
            "url": f"https://music.163.com/#/album?id={item['id']}",
        })
    return out


def download_cover(url: str, album_id: int) -> Optional[Path]:
    if not url:
        return None
    if not config.try_mkdir(CACHE):
        return None
    target = CACHE / f"{album_id}.jpg"
    if target.exists() and target.stat().st_size > 2000:
        return target
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://music.163.com/"})
        with urllib.request.urlopen(request, timeout=25) as resp:
            data = resp.read()
        if len(data) > 2000:
            target.write_bytes(data)
            return target
    except Exception as exc:  # noqa: BLE001
        print(f"封面下载失败 {album_id}: {exc}", file=sys.stderr)
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
        print(f"封面上传失败: {exc}", file=sys.stderr)
        return None
    cache[digest] = key
    if not config.try_mkdir(KEY_CACHE.parent):
        return key
    KEY_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return key


def collect(days: int) -> List[Dict[str, Any]]:
    today = dt.date.today()
    cache = load_artist_cache()
    found: List[Dict[str, Any]] = []
    for name in (CORE_ARTISTS or config.profile_list("core_artists") or CORE_ARTISTS_DEFAULT):
        try:
            artist_id = resolve_artist(name, cache)
        except Exception as exc:  # noqa: BLE001
            print(f"艺人查询失败 {name}: {exc}", file=sys.stderr)
            continue
        if not artist_id:
            print(f"没搜到艺人 {name}", file=sys.stderr)
            continue
        time.sleep(1.2)
        try:
            for album in albums(artist_id, days, today):
                found.append({**album, "artist": name})
        except Exception as exc:  # noqa: BLE001
            print(f"专辑查询失败 {name}: {exc}", file=sys.stderr)
    if config.try_mkdir(ARTIST_CACHE.parent):
        ARTIST_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 同名专辑会被不同艺人重复收录，按 (名字, 日期) 去重
    seen, unique = set(), []
    for album in sorted(found, key=lambda a: a["date"], reverse=True):
        key = (album["name"].lower(), album["date"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(album)
    return unique


def build_card(albums: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
    elements: List[Dict[str, Any]] = []
    for album in albums:
        key = img_key_for(download_cover(album["cover_url"], album["id"]))
        body = (f"**{album['name']}**\n"
                f"<font color='grey'>{album['artist']} · {album['date'][:7]} · {album['tracks']} 曲</font>\n"
                f"[网易云]({album['url']})")
        elements.append(cols((1, [img(key, size="120px 120px", radius="8px")]), (3, [md(body)]))
                        if key else md(body))
        elements.append({"tag": "hr"})
    count = len(CORE_ARTISTS or config.profile_list("core_artists") or CORE_ARTISTS_DEFAULT)
    elements.append(footer(f"近 {days} 天 · 内核层 {count} 位 · 只收 ≥{MIN_TRACKS} 轨的作品 · 不含陪伴型艺人"))
    return card_v2(title="铃 · 新发行", subtitle=f"近 {days} 天 · {len(albums)} 张", template="violet", elements=elements)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--chat", default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--no-send", action="store_true")
    args = parser.parse_args()

    args.chat = args.chat or config.feishu_chat()
    if not args.preview and not args.no_send and not args.chat:
        raise SystemExit("缺少 FEISHU_CHAT_ID")
    albums = collect(args.days)[: args.limit]
    if not albums:
        print(f"近 {args.days} 天内核层没有新作品")
        return 0
    for album in albums:
        print(f"💿 {album['artist']} — {album['name']}（{album['date'][:7]} · {album['tracks']} 曲）")
    if args.preview:
        print(json.dumps(build_card(albums, args.days), ensure_ascii=False, indent=2))
        return 0
    if args.no_send:
        return 0
    try:
        result = send_card(args.chat, build_card(albums, args.days))
        print(f"卡片已发送 {result.get('message_id')}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"发送失败: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
