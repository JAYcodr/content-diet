#!/usr/bin/env python3
"""环境体检：能连哪些源、缺哪些凭据、每张卡在缺凭据时会退化成什么样。

用法::

    python3 setup/doctor.py              # 体检 + 能力矩阵
    python3 setup/doctor.py --fix        # 顺便把 .env 模板写出来
    python3 setup/doctor.py --json       # 机器可读（给 agent 判断用）
    python3 setup/doctor.py --send-test  # 真往 FEISHU_CHAT_ID 发一条，验证投递链路

``--send-test`` 是唯一能证明「机器人在那个群里 + chat_id 没填错」的检查：凭据存在
不等于能送到。凭据填对了但机器没进群，只有真发一次才看得出来。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
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

# wired=False 表示「代码还没读它」：填了不会生效，doctor 不能标成「已配」。
TOKENS = [
    {"key": "FEISHU_APP_ID", "label": "飞书应用 App ID", "level": "必需",
     "loss": "发不了卡片", "wired": True},
    {"key": "FEISHU_APP_SECRET", "label": "飞书应用 App Secret", "level": "必需",
     "loss": "发不了卡片", "wired": True},
    {"key": "FEISHU_CHAT_ID", "label": "接收卡片的会话 ID（oc_…）", "level": "必需",
     "loss": "不知道发给谁", "wired": True},
    {"key": "BGM_API_TOKEN", "label": "Bangumi 个人令牌", "level": "可选",
     "loss": "当前代码没读它（只影响限流，收藏接口尚未接入）；番剧照常能抓", "wired": False},
    {"key": "QIDIAN_COOKIE", "label": "起点登录 Cookie", "level": "可选",
     "loss": "当前代码没读它；在追名单靠访谈档案 + setup/mark.py 回写，不靠 Cookie", "wired": False},
    {"key": "NETEASE_COOKIE", "label": "网易云登录 Cookie", "level": "可选",
     "loss": "暂时用不到，留位", "wired": False},
]

PROXY_HINT = ("若这里报 Network is unreachable / timed out，先设代理再跑：\n"
              "  export CONTENT_DIET_PROXY=http://host:port")


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


def capability_matrix(sources_ok: dict, tokens: dict) -> list:
    """每张卡：需要什么、缺了会怎样。``ready`` 同时看凭据、数据源可达性和档案。"""
    feishu = tokens["feishu"]
    has_core = bool(config.profile_list("core_artists"))
    return [
        {
            "card": "片单卡（番剧 + 网文）",
            "needs": ["飞书凭据", "Bangumi 可达", "起点可达"],
            "degrade": ("缺飞书 → 只打印文本；缺 Bangumi / 起点 → 对应那一段整块缺失、"
                        "另一段照发；已看名单靠档案 + setup/mark.py"),
            "ready": feishu and sources_ok.get("Bangumi", False) and sources_ok.get("起点（移动端）", False),
        },
        {
            "card": "音乐新发行月报",
            "needs": ["飞书凭据", "网易云可达", "档案里 core_artists 非空"],
            "degrade": ("缺内核层名单 → 这张卡直接跳过（不回落默认艺人）；"
                        "缺飞书 → 只打印；缺网易云 → 月报缺失"),
            "ready": feishu and sources_ok.get("网易云音乐", False) and has_core,
        },
        {
            "card": "任天堂新作周报",
            "needs": ["飞书凭据", "任天堂香港可达"],
            "degrade": "缺飞书 → 只打印；其余不缺",
            "ready": feishu and sources_ok.get("任天堂香港", False),
        },
    ]


def send_test() -> int:
    """真发一条卡片：凭据有效 + chat_id 正确 + 机器人确实在群里，三条一次验完。"""
    if not config.has_feishu():
        print("✗ 飞书三项凭据不全（FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_CHAT_ID），先补齐再测")
        return 1
    from core.feishu import card_v2, md, send_card  # 延迟导入：不带 --send-test 时不碰网络

    chat = config.feishu_chat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    card = card_v2(
        title="content-diet · 投递测试",
        subtitle="doctor --send-test",
        template="green",
        elements=[md(f"凭据有效，消息已送达 `{chat}`。\n时间：{now}")],
    )
    try:
        data = send_card(chat, card)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 发送失败：{exc}")
        print("  → 按顺序查三件事：chat_id 是不是 oc_ 开头、机器人有没有被拉进那个群、"
              "应用有没有发过版本并开通 im:message:send_as_bot。")
        return 1
    print(f"✓ 凭据有效，消息已送达 {chat}（message_id {data.get('message_id')}）")
    print("  手机上应该已经收到这张卡；没收到就看机器人是不是在另一个群里。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true", help="把 .env 模板写出来")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--send-test", action="store_true",
                        help="往 FEISHU_CHAT_ID 真发一条卡片，验证投递链路")
    args = parser.parse_args()

    if args.fix and not config.env_path().exists():
        config.save_env({t["key"]: "" for t in TOKENS})
        print(f"已写 .env 模板：{config.env_path()}")

    if args.send_test:
        return send_test()

    env_results = []
    for name, url, purpose, loss in SOURCES:
        ok, detail = probe(url)
        env_results.append({"source": name, "ok": ok, "detail": detail, "purpose": purpose, "loss": loss})

    token_results = []
    for item in TOKENS:
        is_set = bool(config.get(item["key"]))
        token_results.append({**item, "set": is_set,
                              "effective": is_set and item["wired"]})

    sources_ok = {r["source"]: r["ok"] for r in env_results}
    tokens_bool = config.token_status()
    matrix = capability_matrix(sources_ok, tokens_bool)
    home_writable = config.can_write(config.home())
    payload = {
        "home": str(config.home()),
        "home_writable": home_writable,
        "home_hint": "" if home_writable else config.hint(config.home(), "目录不可写"),
        "env_file": str(config.env_path()),
        "env_file_exists": config.env_path().exists(),
        "python": sys.version.split()[0],
        "pillow": _has_pillow(),
        "proxy": config.PROXY,
        "sources": env_results,
        "tokens": token_results,
        "cards": matrix,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"状态目录：{config.home()}"
          + ("" if payload["home_writable"] else "  ⚠ 不可写（只读环境）"))
    if not payload["home_writable"]:
        print("  → " + config.hint(config.home(), "不可写").splitlines()[1])
    if str(config.home()).startswith(str(Path.cwd())):
        print("  提示：状态目录在当前 git 仓库内，已写入的 profile/.env 请确认被 .gitignore 覆盖")
    print(f"凭据文件：{config.env_path()}{'' if config.env_path().exists() else '（还不存在，运行 --fix 生成模板）'}")
    print(f"代理：{config.PROXY or '（未设置 CONTENT_DIET_PROXY，按直连走）'}")
    print(f"Python {payload['python']}｜Pillow：{'有' if payload['pillow'] else '无（任天堂海报拼图需要它）'}")
    print("\n【数据源】")
    for item in env_results:
        print(f"  {'✓' if item['ok'] else '✗'} {item['source']:<12} {item['detail']:<28} "
              f"{'' if item['ok'] else '→ 缺它：' + item['loss']}")
    if any(not item["ok"] for item in env_results) and not config.PROXY:
        print("  " + PROXY_HINT.replace("\n", "\n  "))
    print("\n【凭据】")
    for item in token_results:
        if item["set"] and item["wired"]:
            mark = "✓ 已配"
        elif item["set"]:
            mark = "— 已填写，但代码还没读（留位，暂不生效）"
        else:
            mark = "— 未配（可选）" if item["level"] == "可选" else "✗ 未配（必需）"
        print(f"  {item['key']:<20} {item['label']:<24} {mark}")
        if not item["effective"]:
            print(f"      说明：{item['loss']}")
    print("\n【卡片可用性】")
    for card in matrix:
        print(f"  {'✓' if card['ready'] else '△'} {card['card']}："
              f"{'可以发卡' if card['ready'] else '还差条件（见下）'}")
        print(f"      需要：{'、'.join(card['needs'])}")
        print(f"      {card['degrade']}")
    print("\n下一步：补必需凭据 → `python3 setup/doctor.py --send-test` 真发一条 → "
          "`python3 setup/init.py --answers answers.json`")
    return 0


def _has_pillow() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    sys.exit(main())
