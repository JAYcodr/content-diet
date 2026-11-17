#!/usr/bin/env python3
"""任天堂（香港）发售日程抓取 + 初筛。

只做确定性的活：抓页面 → 解析 → 按发行商初筛 → 挑出「上次之后新增的」→ 落盘海报。
判断「是不是 AI 垃圾」留给调用方（agent 看海报），本脚本只用名单和标签做粗筛，
每条都带 `why` 说明是哪个规则命中的，方便回查。

用法::

    nintendo_hk.py --new            # 只输出新增条目（JSON，键 games），同时下载海报
    nintendo_hk.py --all            # 输出全部条目（不入状态、不写 pending）
    nintendo_hk.py --commit         # 把上一次 --new 输出的条目记入 seen（发完卡片再调）
    nintendo_hk.py --commit --from-payload payload.json   # 或按指定 payload 提交
    nintendo_hk.py --publishers     # 看发行商排行，便于维护名单

``--commit`` 只提交「真处理过」的条目：payload 里的（发过卡 / agent 审过的）+ 判为 drop 的。
白名单 keep 但这一轮没发出去的、没审的 review 都不进 seen，下周还会再出现。
``--commit --all`` 已禁用：它会把没发出去的条目一次性标成已见。

状态与海报都在 $CONTENT_DIET_HOME/nintendo/ 下
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEDULE_URL = "https://www.nintendo.com/hk/schedule"

_ROOT = Path(__file__).resolve().parent.parent      # 直接 python3 sources/xxx.py 也能 import core
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import config  # noqa: E402

CACHE = config.state_dir("nintendo")
SEEN = CACHE / "seen.json"
PENDING = CACHE / "pending.json"
POSTERS = CACHE / "posters"
PROXY = config.PROXY
CST = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 大厂/知名发行：一定送审（不是"一定推"，agent 再判断值不值得写进卡片）
WHITELIST = [
    "nintendo", "square enix", "capcom", "bandai namco", "sega", "atlus", "koei tecmo",
    "konami", "shift up", "clouded leopard", "hoyoverse", "mihoyo", "snk", "arc system works",
    "falcom", "nis america", "idea factory", "spike chunsoft", "level-5", "ubisoft",
    "electronic arts", "2k", "take-two", "rockstar", "cd projekt", "devolver", "annapurna",
    "team17", "playism", "flyhigh works", "marvelous", "good smile", "microids", "atari",
    "activision", "blizzard", "warner", "focus entertainment", "thq nordic", "prime matter",
]

# 典型 shovelware / 资产翻新 / AI 图小作发行商。命中直接丢，不占用审阅预算。
# 名单是经验值，靠 --why 与 --publishers 随时校正；宁可漏杀，不可错杀大厂。
BLACKLIST = [
    "red fables", "randomspin games", "17studio", "gametry", "upscale studio", "dev 666",
    "hgames-artworks", "merge conflict studio", "pdpartid@games", "ethan froom",
    "brainium games", "lunaria games", "eathrabaria", "am factory", "eihsoft",
    "alcedo games", "picnic play", "age", "tt", "mask",
]

# 标题里的高噪声词（配合"非白名单发行商"才生效，白名单里的标题不受影响）
NOISE_WORDS = ["catgirl", "backrooms", "hentai", "harem", "jigsaw", "merge ", "simulator",
               "模擬器", "拼圖", "拼图", "突破天際", "禁忌", "慾望", "欲望"]

OUT = re.compile(
    r'(?:local-schedule__monthHeaderText">(?P<month>[^<]+)<)'
    r'|(?:local-schedule__dayFull">(?P<day>[\d.]+))'
    r'|(?:<a href="(?P<href>https://ec\.nintendo\.com/HK/zh/titles/[^"]+)"(?P<body>.*?)</a>)',
    re.S)
IMG = re.compile(r"background-image:\s*url\(([^\"')\s]+)")
LABEL = re.compile(r'local-schedule__labelText"><span>(?P<v>[^<]*)<')
TITLE = re.compile(r'local-schedule__listTitle"><strong>(?P<v>.*?)</strong>', re.S)
PUB = re.compile(r'<span>\[<!-- -->(?P<v>.*?)<!-- -->\]')


def _get(url: str, timeout: float = 30.0) -> bytes:
    last: Optional[Exception] = None
    for proxy in (None, PROXY):
        try:
            if proxy:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            else:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"抓取失败 {url}: {last}")


def parse(html: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    month = day = None
    for match in OUT.finditer(html):
        if match.group("month"):
            month = match.group("month").strip()
            continue
        if match.group("day"):
            day = match.group("day").strip()
            continue
        body = match.group("body") or ""
        title = TITLE.search(body)
        if not title:
            continue
        poster = IMG.search(body)
        publisher = PUB.search(body)
        items.append({
            "id": match.group("href").rstrip("/").split("/")[-1],
            "title": html_lib.unescape(re.sub(r"<[^>]+>", "", title.group("v")).strip()),
            "publisher": html_lib.unescape(publisher.group("v").strip()) if publisher else "",
            "label": LABEL.search(body).group("v").strip() if LABEL.search(body) else "",
            "date": day,
            "month": month,
            "poster_url": poster.group(1).replace("&amp;", "&") if poster else "",
            "url": match.group("href"),
        })
    return items



# ---------------------------------------------------------------- 口味信号
# 口味分层的依据是 profile.json（由 setup/init.py 生成）。
# 只做"排序 + 明显排除"，不做题材审查：恐怖、无双、射击这类只标 caution，不丢。
TASTE_HIT_SERIES = [
    "薩爾達", "塞尔达", "異度神劍", "异度神剑", "皮克敏", "卡比", "動森", "动物森友",
    "寶可夢", "宝可梦", "牧場物語", "牧场物语", "符文工房", "星露谷", "殺戮尖塔", "杀戮尖塔",
    "哈迪斯", "十三機兵", "火焰紋章", "火焰纹章", "三角戰略", "潜水员", "潛水員",
    "魔物獵人", "怪物猎人", "勇者鬥惡龍", "勇者斗恶龙", "女神異聞錄", "女神异闻录",
    "final fantasy", "最終幻想", "最终幻想", "空之軌跡", "逆轉裁判", "逆转裁判",
]
TASTE_HIT_GENRE = [
    "模擬", "模拟", "經營", "经营", "農場", "农场", "種田", "种田", "牧場", "牧场",
    "戰棋", "战棋", "回合", "解謎", "解谜", "箱庭", "卡牌", "卡組", "构筑", "肉鴿", "肉鸽",
    "养成", "養成", "釣魚", "钓鱼", "料理", "桌遊", "桌游",
]
TASTE_AVOID = ["排位", "電競", "电竞", "pvp", "大逃殺", "大逃杀", "吃雞", "吃鸡", "多人競技", "多人竞技"]
TASTE_CAUTION = ["恐怖", "horror", "射擊", "射击", "無雙", "无双", "建造", "沙盒"]

# 档案里可以追加词（profile.json）：
#   game_series  系列名（权重等同内置系列）
#   game_hits    品类词（权重等同内置品类）
#   game_avoid   口味禁区（命中直接 drop）
#   game_caution 要提醒但不丢（如恐怖、射击）
_TASTE: Optional[Dict[str, List[str]]] = None


def taste_lists() -> Dict[str, List[str]]:
    """内置词表 ∪ 档案词表。改档案里的词，下一次跑就影响命中/禁区结果。"""
    global _TASTE
    if _TASTE is None:
        _TASTE = {
            "series": list(TASTE_HIT_SERIES) + [str(x) for x in config.profile_list("game_series")],
            "genre": list(TASTE_HIT_GENRE) + [str(x) for x in config.profile_list("game_hits")],
            "avoid": list(TASTE_AVOID) + [str(x) for x in config.profile_list("game_avoid")],
            "caution": list(TASTE_CAUTION) + [str(x) for x in config.profile_list("game_caution")],
        }
    return _TASTE


def refresh_taste() -> None:
    """改完档案想让同一个进程重算时调用（cron 每次新进程，通常用不到）。"""
    global _TASTE
    _TASTE = None


def taste(item: Dict[str, Any]) -> Dict[str, str]:
    """口味分层：hit（系列/品类命中）/ avoid（长期竞技打卡）/ caution（要提醒但不禁）/ neutral。"""
    words = taste_lists()
    haystack = f"{item['title']} {item.get('publisher','')}".lower()
    for word in words["avoid"]:
        if word and word.lower() in haystack:
            return {"taste": "avoid", "taste_note": f"长期竞技/打卡，命中口味禁区（{word}）"}
    hits = [w for w in words["series"] if w and w.lower() in haystack]
    if hits:
        return {"taste": "hit", "taste_note": f"口味命中：{hits[0]}"}
    hits = [w for w in words["genre"] if w and w.lower() in haystack]
    if hits:
        return {"taste": "hit", "taste_note": f"品类命中：{hits[0]}"}
    caution = [w for w in words["caution"] if w and w.lower() in haystack]
    if caution:
        return {"taste": "caution", "taste_note": f"口味留意：{caution[0]}（未必禁区，按手法判断）"}
    return {"taste": "neutral", "taste_note": ""}


def classify(item: Dict[str, Any]) -> Dict[str, Any]:
    """粗筛：给每条打 why。verdict 取 keep / review / drop。"""
    pub = (item["publisher"] or "").lower()
    title = (item["title"] or "").lower()
    if any(w and w == pub for w in WHITELIST):
        return {"verdict": "keep", "why": f"白名单发行商 {item['publisher']}", **taste(item)}
    if any(w and w == pub for w in BLACKLIST):
        return {"verdict": "drop", "why": f"黑名单发行商 {item['publisher']}", **taste(item)}
    noise = [w for w in NOISE_WORDS if w in title]
    if noise:
        return {"verdict": "drop", "why": f"标题含噪声词 {'/'.join(noise[:2])}", **taste(item)}
    flavor = taste(item)
    if flavor["taste"] == "avoid":
        return {"verdict": "drop", "why": flavor["taste_note"], **flavor}
    if flavor["taste"] == "hit":
        # 口味命中优先送去审海报（预算内排在前面），但仍要过我这一眼，不无条件进卡
        return {"verdict": "review", "why": flavor["taste_note"], "priority": True, **flavor}
    return {"verdict": "review", "why": "未列入名单，需看海报判断", **flavor}


def poster_path(item: Dict[str, Any]) -> Optional[Path]:
    """下载海报（转成 jpg，飞书上传更稳），返回本地路径。"""
    url = item.get("poster_url") or ""
    if not url:
        return None
    if not config.try_mkdir(POSTERS):
        return None
    target = POSTERS / f"{item['id']}.jpg"
    if target.exists() and target.stat().st_size > 1000:
        return target
    url = re.sub(r"fm=\w+", "fm=jpg", url)
    try:
        data = _get(url, timeout=25.0)
    except Exception as exc:  # noqa: BLE001
        print(f"海报下载失败 {item['id']}: {exc}", file=sys.stderr)
        return None
    if len(data) < 1000:
        return None
    target.write_bytes(data)
    return target


def dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一款游戏常在「下載版」「實體版」各出现一次：按 id 合并，标签拼接。"""
    merged: Dict[str, Dict[str, Any]] = {}
    by_title: Dict[tuple, str] = {}
    for item in items:
        key = (item["title"].lower(), item["publisher"].lower())
        if key in by_title:            # 同一款以「Nintendo Switch 2 Edition」等名义重复出现
            item = {**item, "id": by_title[key]}
        else:
            by_title[key] = item["id"]
        old = merged.get(item["id"])
        if not old:
            merged[item["id"]] = dict(item)
            continue
        labels = {part.strip() for part in (old["label"] + " / " + item["label"]).split("/") if part.strip()}
        old["label"] = " / ".join(sorted(labels))
    return list(merged.values())


def in_window(item: Dict[str, Any], days: int, today: Optional[datetime] = None) -> bool:
    """发售日在未来 days 天内（含未定日期）。日期形如 2026.11.5。"""
    raw = item.get("date") or ""
    if not re.fullmatch(r"\d{4}\.\d{1,2}\.\d{1,2}", raw or ""):
        return True
    y, m, d = (int(x) for x in raw.split("."))
    try:
        when = datetime(y, m, d, tzinfo=CST)
    except ValueError:
        return True
    now = today or datetime.now(CST)
    delta = (when - now).days
    return -7 <= delta <= days


def load_seen() -> Dict[str, Any]:
    if SEEN.exists():
        try:
            return json.loads(SEEN.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"ids": [], "last_run": None}


def save_seen(seen: Dict[str, Any]) -> None:
    if not config.try_mkdir(CACHE):
        print("状态目录不可写，跳过记基线（下次会重复推）", file=sys.stderr)
        return
    seen["last_run"] = datetime.now(CST).isoformat(timespec="seconds")
    SEEN.write_text(json.dumps(seen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_pending(payload: Dict[str, Any]) -> None:
    """记住上一次 ``--new`` 到底输出了什么——``--commit`` 只按这份记录提交。"""
    if not config.try_mkdir(CACHE):
        return
    PENDING.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def payload_ids(payload: Dict[str, Any]) -> set:
    """接受 ``games`` 与旧键 ``items``，两种都能读。"""
    items = payload.get("games")
    if items is None:
        items = payload.get("items")
    return {str(g["id"]) for g in (items or []) if isinstance(g, dict) and g.get("id")}


def load_pending() -> Dict[str, Any]:
    if not PENDING.exists():
        return {}
    try:
        return json.loads(PENDING.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--new", action="store_true", help="只输出新增（默认）")
    parser.add_argument("--all", action="store_true", help="输出全部")
    parser.add_argument("--commit", action="store_true", help="把 --new 的条目记入 seen")
    parser.add_argument("--publishers", action="store_true", help="发行商排行")
    parser.add_argument("--no-posters", action="store_true", help="不下载海报")
    parser.add_argument("--days", type=int, default=45, help="只看未来多少天内发售，默认 45")
    parser.add_argument("--limit-review", type=int, default=8, help="review 条目最多留几条，默认 8")
    parser.add_argument("--from-payload", help="配合 --commit：只提交 payload 里的 + 非 review 的条目")
    args = parser.parse_args()

    html = _get(SCHEDULE_URL).decode("utf-8", "replace")
    items = parse(html)
    if not items:
        print("解析到 0 条，页面结构可能变了", file=sys.stderr)
        return 2

    if args.publishers:
        from collections import Counter
        for pub, count in Counter(i["publisher"] for i in items).most_common(40):
            mark = "白" if pub.lower() in WHITELIST else ("黑" if pub.lower() in BLACKLIST else "  ")
            print(f"{mark} {count:>3}  {pub}")
        return 0

    items = dedupe(items)
    seen = load_seen()
    known = set(seen.get("ids") or [])
    fresh = items if args.all else [i for i in items if i["id"] not in known]
    fresh = [i for i in fresh if in_window(i, args.days)]
    rank = {"hit": 0, "neutral": 1, "caution": 2, "avoid": 3}
    def sort_key(item: Dict[str, Any]):
        verdict = classify(item)
        return (0 if verdict["verdict"] == "keep" else 1,
                0 if verdict.get("priority") else 1,
                rank.get(verdict["taste"], 1),
                item["date"] or "9999.99.99")
    fresh.sort(key=sort_key)

    reviewed = 0
    out: List[Dict[str, Any]] = []
    for item in fresh:
        verdict = classify(item)
        record = {**item, **verdict}
        if args.commit:
            continue
        if verdict["verdict"] == "drop":
            continue          # 黑名单 / 噪声词：只在 commit 时记进 seen，不进 payload、不进卡片
        if verdict["verdict"] == "review":
            reviewed += 1
            if reviewed > args.limit_review:
                continue  # 超出审阅预算的先不打扰，下次还能看到
        if not args.no_posters:
            path = poster_path(item)
            record["poster_file"] = str(path) if path else None
        out.append(record)

    if args.commit:
        if args.all:
            print("--commit 不再接受 --all：它会把这一轮窗口里没发出去的条目（白名单 keep、"
                  "没审的 review）一次性记成已见，下周就不再出现。\n"
                  "改成 --commit（提交上一次 --new 的输出）或 --commit --from-payload <path>。",
                  file=sys.stderr)
            return 2
        fresh_ids = {i["id"] for i in fresh}
        if args.from_payload:
            try:
                payload = json.loads(Path(args.from_payload).read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                print(f"读 payload 失败：{exc}", file=sys.stderr)
                return 2
            target_ids = payload_ids(payload)
        else:
            target_ids = payload_ids(load_pending())
            if not target_ids:
                print("没有可提交的记录：先跑一次 --new（它会写 pending.json），"
                      "或直接 --commit --from-payload <path>。", file=sys.stderr)
                return 2
        # 只提交「真处理过」的：payload 里的（发过卡 / agent 审过的）+ 判为 drop 的
        # （黑名单是稳定判断，记下来不会误伤下周的候选）。白名单 keep 但没发出去的不记。
        drops = {i["id"] for i in fresh if classify(i)["verdict"] == "drop"}
        committed = (target_ids & fresh_ids) | drops
        seen["ids"] = sorted(known | committed)
        save_seen(seen)
        print(f"已记入 seen：本次 {len(committed)} 条（payload {len(target_ids & fresh_ids)} + "
              f"drop {len(drops)}），累计 {len(seen['ids'])} 条")
        return 0

    payload = {
        "fetched_at": datetime.now(CST).isoformat(timespec="seconds"),
        "total_on_page": len(items),
        "new_count": len(fresh),
        # 契约键是 games，items 是同一份数据的旧键（兼容上一版 cards.games / poster_sheet）
        "games": out,
        "items": out,
    }
    if not args.all:
        save_pending(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
