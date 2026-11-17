#!/usr/bin/env python3
"""按用户口味给番剧打分（数据源：Bangumi 公开 API，免费、无 key）。

口味依据 profile.json（由 setup/init.py 生成）。评分是三段相加：
  * 命中向（系列/品类/梗）加分
  * 已看清单（他确认过的作品）直接排除
  * Bangumi 评分作为质量地板，低于阈值不推

用法::

    anime_pick.py --airing            # 本季在播（Bangumi 日历）
    anime_pick.py --rank --year 2026  # 某个年份的高分作品
    anime_pick.py --airing --limit 12

输出 JSON：{picked:[{name_cn,name,score,bgm_score,reasons,tags,url,image}], skipped:N}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parent.parent      # 直接 python3 <script> 也能 import core
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import config  # noqa: E402

API = "https://api.bgm.tv"
PROXY = config.PROXY
UA = "hermes-agent/1.0 (anime-pick; personal use)"

# 命中向：系列/作者/母题。权重 3 = 强命中，2 = 中，1 = 弱
HITS: Dict[str, int] = {
    # 京阿尼系
    "京都アニメーション": 3, "kyoto animation": 3, "京阿尼": 3,
    # 系统自洽 / 慢烧 / 时间循环 / 硬科幻
    "时间循环": 3, "轮回": 2, "loop": 2, "硬科幻": 3, "science fiction": 1,
    "推理": 2, "悬疑": 2, "群像": 2, "シニカル": 1,
    # 种田 / 经营 / 日常仪式
    "日常": 1, "治愈": 2, "种田": 3, "经营": 3, "グルメ": 2, "美食": 2, "料理": 2,
    # 政治博弈 / 战争 / 社会系统
    "政治": 3, "戦争": 2, "战争": 2, "反战": 2, "ディストピア": 3, "反乌托邦": 3,
    "ロボット": 2, "机甲": 2, "mecha": 2, "sf": 1,
    # 情感延迟传递
    "青春": 1, "subtle": 1, "microexpression": 1, "文芸": 2, "文艺": 2,
    # 残酷系统 × 真实成长
    "成长": 2, "代价": 2, "群像剧": 2,
    # 音乐放大器
    "音乐": 2, "音楽": 2, "吹奏乐": 2, "バンド": 1,
    # Bangumi 中文标签
    "推理": 2, "悬疑": 2, "科幻": 2, "日常": 1, "治愈": 2, "美食": 2, "料理": 2,
    "群像": 2, "历史": 2, "政治": 3, "战争": 1, "职场": 1, "经营": 3, "种田": 3,
    "体育": 1, "音乐": 2, "漫画改": 0,
    # 后宫可以，但要有博弈/群像撑；单靠后宫不加分
    "后宫": 0, "ハーレム": 0,
}

# 明确忌讳：龙傲天、降智爽文、纯恐怖惊吓、长期竞技。
# **后宫不在忌讳里**（评论里已说明「后宫可以，但要有博弈/群像撑」，所以它只在 HITS 里记 0 分，
# 不能既给 0 分又扣 4 分——那等于把一条中性标签当成禁区）。
AVOID: Dict[str, str] = {
    "龙傲天": "降智爽文", "無双": "开挂向", "无双": "开挂爽剧", "爽文": "降智爽文",
    "jump scare": "惊吓驱动",
    "eスポーツ": "竞技打卡", "电竞": "竞技打卡", "アイドル": "偶像营业向",
    "卖肉": "肉番", "赌博": "赌博题材（需人工判断是否有系统自洽）",
}

MIN_BGM_SCORE = 6.2   # Bangumi 评分地板


def get(path: str, params: Dict[str, Any] | None = None) -> Any:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last: Exception | None = None
    for proxy in (None, PROXY):
        try:
            opener = (urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
                      if proxy else urllib.request.build_opener(urllib.request.ProxyHandler({})))
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with opener.open(request, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"Bangumi 请求失败 {url}: {last}")



def season_of_today() -> tuple[int, int]:
    """当前季度：(年, 季首月)。1/4/7/10 月算季首。"""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=8)))
    month = (now.month - 1) // 3 * 3 + 1
    return now.year, month


def season_range(year: int, month: int) -> tuple[str, str]:
    """季度起止：2026-10-01 ~ 2027-01-01。"""
    end_month = month + 3
    end_year = year + (1 if end_month > 12 else 0)
    end_month = end_month - 12 if end_month > 12 else end_month
    return f"{year}-{month:02d}-01", f"{end_year}-{end_month:02d}-01"


def search_subjects(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """POST /v0/search/subjects（带标签与评分），失败再退回 /calendar。"""
    url = f"{API}/v0/search/subjects?limit=50"
    body = json.dumps(payload).encode()
    last = None
    for proxy in (None, PROXY):
        try:
            opener = (urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
                      if proxy else urllib.request.build_opener(urllib.request.ProxyHandler({})))
            request = urllib.request.Request(url, data=body, method="POST", headers={
                "User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"})
            with opener.open(request, timeout=40) as resp:
                return json.loads(resp.read().decode("utf-8", "replace")).get("data") or []
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"Bangumi 搜索失败: {last}")


def fields(subject: Dict[str, Any]) -> tuple[str, str]:
    """(标签串, 标题串)。简介不参与打分——里面随手一提「料理」会把无关作品顶上来。"""
    tags = []
    for tag in subject.get("tags") or []:
        tags.append(str(tag.get("name") if isinstance(tag, dict) else tag))
    title = f"{subject.get('name_cn') or ''} {subject.get('name') or ''}"
    return " ".join(tags).lower(), title.lower()


def hit_terms() -> Dict[str, int]:
    """内置命中词 + 档案 ``anime_hits``（用户自己补的词，权重 2）。"""
    terms = dict(HITS)
    for word in config.profile_list("anime_hits"):
        word = str(word).strip()
        if word and word.lower() not in terms:
            terms[word.lower()] = 2
    return terms


def avoid_terms() -> Dict[str, str]:
    """内置忌讳 + 档案 ``anime_avoid``——档案里的排斥信号**逐条生效**，不是只写给人看。"""
    terms = dict(AVOID)
    for word in config.profile_list("anime_avoid"):
        word = str(word).strip()
        if word and word.lower() not in terms:
            terms[word.lower()] = f"档案排斥信号（{word}）"
    return terms


def score(subject: Dict[str, Any]) -> Dict[str, Any]:
    tag_text, title_text = fields(subject)
    bgm = float((subject.get("rating") or {}).get("score") or 0)
    reasons: List[str] = []
    total = 0.0
    for word, weight in hit_terms().items():
        key = word.lower()
        if key in tag_text:
            total += weight
            reasons.append(f"+{weight} {word}(标签)")
        elif key in title_text:
            total += weight / 2          # 只在标题里命中，折半
            reasons.append(f"+{weight / 2:.1f} {word}(标题)")
    for word, why in avoid_terms().items():
        key = word.lower()
        if key in tag_text or key in title_text:
            total -= 4
            reasons.append(f"-4 {why}")
    if bgm >= 8.0:
        total += 2
        reasons.append(f"+2 Bangumi {bgm}（口碑强）")
    elif bgm >= MIN_BGM_SCORE:
        total += 1
        reasons.append(f"+1 Bangumi {bgm}")
    return {"score": round(total, 1), "bgm_score": bgm, "reasons": reasons}


_WATCHED: Optional[set] = None


def watched() -> set:
    """已看集合：档案的 anime_watched / anime_watched_all ∪ feedback 的 anime.seen/skip。

    ``refresh()`` 让回写之后同一个进程里也能生效（cron 每次是新进程，但测试和手动补跑会用得上）。
    """
    global _WATCHED
    if _WATCHED is None:
        names = [str(x) for x in config.profile_list("anime_watched")]
        names += [str(x) for x in config.profile_list("anime_watched_all")]
        names += config.feedback_excludes("anime")
        _WATCHED = {n.strip().lower() for n in names if n and n.strip()}
    return _WATCHED


def refresh() -> None:
    """丢掉已看集合的缓存（回写 / 改档案之后调用）。"""
    global _WATCHED
    _WATCHED = None


def seen(subject: Dict[str, Any]) -> bool:
    text = f"{subject.get('name_cn') or ''} {subject.get('name') or ''}".lower()
    return any(word and word in text for word in watched())


def collect(mode: str, year: str | None, limit: int) -> Dict[str, Any]:
    subjects: List[Dict[str, Any]] = []
    if mode == "airing":
        year, month = season_of_today()
        start, end = season_range(year, month)
        payload = {"keyword": "", "sort": "heat",
                   "filter": {"type": [2], "air_date": [f">={start}", f"<{end}"], "nsfw": False}}
        subjects = search_subjects(payload)[:60]
    else:
        data = get("/v0/subjects", {"type": 2, "sort": "rank", "limit": 100,
                                    **({"year": year} if year else {})})
        subjects = data.get("data") or []

    picked, skipped = [], 0
    for subject in subjects:
        if seen(subject):
            skipped += 1
            continue
        result = score(subject)
        if mode == "rank" and result["bgm_score"] and result["bgm_score"] < MIN_BGM_SCORE:
            skipped += 1
            continue
        if result["score"] <= 0:
            skipped += 1
            continue
        subject.update(result)
        picked.append(subject)

    picked.sort(key=lambda s: (s["score"], s["bgm_score"]), reverse=True)
    out = []
    for subject in picked[:limit]:
        out.append({
            "id": subject.get("id"),
            "name": subject.get("name_cn") or subject.get("name"),
            "name_jp": subject.get("name"),
            "bgm_score": subject["bgm_score"],
            "score": subject["score"],
            "reasons": subject["reasons"],
            "summary": (subject.get("summary") or "")[:180],
            "url": subject.get("url") or f"https://bgm.tv/subject/{subject.get('id')}",
            "image": (subject.get("images") or {}).get("large") or "",
        })
    return {"mode": mode, "candidates": len(subjects), "skipped": skipped, "picked": out}


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--airing", action="store_true", help="本季在播")
    group.add_argument("--rank", action="store_true", help="按 Bangumi 排行")
    parser.add_argument("--year", default=None)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    payload = collect("airing" if args.airing else "rank", args.year, args.limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
