#!/usr/bin/env python3
"""环境体检：能连哪些源、缺哪些凭据、每张卡在缺凭据时会退化成什么样。

用法::

    python3 setup/doctor.py            # 体检 + 能力矩阵
    python3 setup/doctor.py --fix      # 顺便把 .env 模板写出来
    python3 setup/doctor.py --json     # 机器可读（给 agent 判断用）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402

UA = "content-diet/1.0 (doctor)"

# 每个源：名称 / 探测地址 / 说明 / 没有它时少什么
SOURCES = [
    ("Bangumi", "https://api.bgm.tv/calendar", "番剧当季榜与评分", "番剧段整块缺失"),
    ("起点（移动端）", "https://m.qidian.com/rank/yuepiao", "网文月票榜与简介", "网文段整块缺失"),
    ("网易云音乐", "https://music.163.com/api/search/get/web?s=a&type=100&limit=1", "艺人专辑清单与封面", "音乐月报缺失"),
    ("任天堂香港", "https://www.nintendo.com/hk/schedule", "新作发售表与海报", "任天堂周报缺失"),
    ("飞书开放平台", "https://open.feishu.cn/", "卡片投递", "无法发卡片（只能打印到 stdout）"),
]

TOKENS = [
    ("FEISHU_APP_ID", "飞书应用 App ID", "必需", "发不了卡片"),
    ("FEISHU_APP_SECRET", "飞书应用 App Secret", "必需", "发不了卡片"),
    ("FEISHU_CHAT_ID", "接收卡片的会话 ID（oc_…）", "必需", "不知道发给谁"),
    ("BGM_API_TOKEN", "Bangumi 个人令牌", "可选", "番剧仍能抓，但看不了你的收藏、限额更低"),
    ("QIDIAN_COOKIE", "起点登录 Cookie", "可选", "网文按榜单推荐，但不知道你在追什么（会重复推）"),
    ("NETEASE_COOKIE", "网易云登录 Cookie", "可选", "不影响月报；暂时用不到，留位"),
]


def probe(url: str, timeout: float = 12.0) -> tuple:
    """直连一次，失败再走代理一次。返回 (ok, 说明)。"""
    last = ""
    proxies = [None]
    if config.PROXY:
        proxies.append(config.PROXY)
    for proxy in proxies:
        try:
            if proxy:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            else:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with opener.open(req, timeout=timeout) as resp:
                return True, f"HTTP {resp.status}（{'代理' if proxy else '直连'}）"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:80]
    return False, last


def capability_matrix() -> list:
    """每张卡：需要什么、缺了会怎样。"""
    tokens = config.token_status()
    return [
        {
            "card": "片单卡（番剧 + 网文）",
            "needs": ["飞书凭据", "Bangumi 可达", "起点可达"],
            "degrade": ("缺飞书 → 只打印文本；缺 BGM_TOKEN → 番剧不禁看过的；"
                        "缺起点 Cookie → 可能推你在追的书"),
            "ready": tokens["feishu"],
        },
        {
            "card": "音乐新发行月报",
            "needs": ["飞书凭据", "网易云可达", "内核层艺人名单（init 里有）"],
            "degrade": "缺内核层名单 → 不排这张卡；缺飞书 → 只打印",
            "ready": tokens["feishu"],
        },
        {
            "card": "任天堂新作周报",
            "needs": ["飞书凭据", "任天堂香港可达"],
            "degrade": "缺飞书 → 只打印；其余不缺",
            "ready": tokens["feishu"],
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true", help="把 .env 模板写出来")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.fix and not config.env_path().exists():
        config.save_env({k: "" for k, _, _, _ in TOKENS})
        print(f"已写 .env 模板：{config.env_path()}")

    env_results = []
    for name, url, purpose, loss in SOURCES:
        ok, detail = probe(url)
        env_results.append({"source": name, "ok": ok, "detail": detail, "purpose": purpose, "loss": loss})

    token_results = []
    for key, label, level, loss in TOKENS:
        token_results.append({"key": key, "label": label, "level": level,
                              "set": bool(config.get(key)), "loss": loss})

    matrix = capability_matrix()
    payload = {
        "home": str(config.home()),
        "env_file": str(config.env_path()),
        "env_file_exists": config.env_path().exists(),
        "python": sys.version.split()[0],
        "pillow": _has_pillow(),
        "sources": env_results,
        "tokens": token_results,
        "cards": matrix,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"状态目录：{config.home()}")
    print(f"凭据文件：{config.env_path()}{'' if config.env_path().exists() else '（还不存在，运行 --fix 生成模板）'}")
    print(f"Python {payload['python']}｜Pillow：{'有' if payload['pillow'] else '无（任天堂海报拼图需要它）'}")
    print("\n【数据源】")
    for item in env_results:
        print(f"  {'✓' if item['ok'] else '✗'} {item['source']:<12} {item['detail']:<28} "
              f"{'' if item['ok'] else '→ 缺它：' + item['loss']}")
    print("\n【凭据】")
    for item in token_results:
        mark = "✓ 已配" if item["set"] else ("— 未配（可选）" if item["level"] == "可选" else "✗ 未配（必需）")
        print(f"  {item['key']:<20} {item['label']:<24} {mark}")
        if not item["set"]:
            print(f"      缺它：{item['loss']}")
    print("\n【卡片可用性】")
    for card in matrix:
        print(f"  {'✓' if card['ready'] else '△'} {card['card']}：{'可发卡片' if card['ready'] else '只能打印文本'}")
        print(f"      {card['degrade']}")
    print("\n下一步：按 references/tokens.md 补必需凭据，然后 `python3 setup/init.py --answers answers.json`")
    return 0


def _has_pillow() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    sys.exit(main())
