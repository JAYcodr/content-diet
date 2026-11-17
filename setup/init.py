#!/usr/bin/env python3
"""把一个「口味访谈」的结果落成 profile.json + taste_profile.md，并打印排期建议。

这个脚本**不做交互**——访谈由 agent 完成（见 SKILL.md 与 setup/interview.md），
agent 把答案整理成 JSON 传进来即可，这样跳过 / 大概 / 普通 / 细致 四档都能走同一条路。

用法::

    python3 setup/init.py --answers answers.json
    python3 setup/init.py --answers answers.json --dry-run     # 只看会写出什么
    python3 setup/init.py --example                            # 打印答案模板

answers.json 结构见 setup/init.py --example 与 references/taste-schema.md。
缺失的字段会留空，后续卡片按空值降级（不报错）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402

DEFAULTS = {
    "depth": "normal",
    "name": "",
    "lines": {},
    "anime_watched": [],
    "anime_avoid": [],
    "anime_hits": [],
    "novels_read": [],
    "novels_dropped": [],
    "novel_categories": [],
    "novel_authors": {},
    "core_artists": [],
    "companion_artists": [],
    "music_avoid": [],
    "game_series": [],
    "game_hits": [],
    "game_avoid": [],
    "game_caution": [],
    "voice": {},
    "notes": "",
}

TEMPLATE = """# 口味档案（{name}）

> 由 content-diet 初始化生成于 {date}。**参考，不是圣经**——口味会变，边界情况宁可留着让本人剔。

## 审美主线

{lines_block}

## 体验距离

{principle_block}

## 排斥信号

{avoid_block}

## 番剧

- 已看（用于排重）：{watched}
- 不看：{anime_avoid}

## 网文

- 已读 / 在追：{novels_read}
- 弃书：{novels_dropped}
- 偏好分类：{novel_categories}

## 音乐

- 内核层（主推区，会推新发行）：{core_artists}
- 陪伴型（**不推**，推了是噪音）：{companion_artists}
- 排斥：{music_avoid}

## 声音 / 有声

{voice_block}

## 备注

{notes}
"""


def example() -> dict:
    return {
        **DEFAULTS,
        "depth": "normal",
        "name": "文杰",
        "lines": {
            "A": "史诗时间感：大时间尺度下的个体命运",
            "B": "延迟情感传递：情感要介质、有距离",
            "C": "残酷系统 × 真实成长：拒绝无逻辑开挂",
            "D": "温系统 × 日常仪式 × 自我节奏",
        },
        "anime_watched": ["葬送的芙莉莲", "摇曳露营", "孤独摇滚"],
        "anime_avoid": ["长期 PVP 打卡", "第一人称生存恐怖"],
        "anime_hits": ["吹奏乐", "政治博弈"],
        "novels_read": ["黎明之剑", "这游戏也太真实了"],
        "novels_dropped": ["玄鉴仙族"],
        "novel_categories": ["科幻", "轻小说"],
        "novel_authors": {"远瞳": 5, "爱潜水的乌贼": 3},
        "core_artists": ["Aimer", "ヨルシカ"],
        "companion_artists": ["周杰伦", "林俊杰"],
        "music_avoid": ["电音 drop", "偶像团口水副歌"],
        "game_series": ["薩爾達", "異度神劍"],
        "game_hits": ["模擬", "戰棋"],
        "game_avoid": ["排位", "大逃殺"],
        "game_caution": ["恐怖", "射擊"],
        "voice": {"anchor": "今汐", "f0": "200-260Hz", "centroid": "1600-2100Hz", "note": "低音区+窄音域+气声颗粒"},
        "notes": "旁白不要给表演指令；角色台词一句一条。",
    }


def join(items) -> str:
    if not items:
        return "（未填）"
    return "、".join(str(x) for x in items)


def render(answers: dict, name: str) -> str:
    import datetime as dt

    lines = answers.get("lines") or {}
    lines_block = "\n".join(
        f"- **{key}**：{value}" for key, value in lines.items()
    ) or "（未填，卡片会按通用口味排序）"
    voice = answers.get("voice") or {}
    voice_block = "\n".join(f"- {k}: {v}" for k, v in voice.items()) or "（未填）"
    return TEMPLATE.format(
        name=name,
        date=dt.date.today().isoformat(),
        lines_block=lines_block,
        principle_block=answers.get("principle") or "（未填：默认「有距离 + 有控制权」优先）",
        avoid_block=join(answers.get("anime_avoid")),
        watched=join(answers.get("anime_watched")),
        anime_avoid=join(answers.get("anime_avoid")),
        novels_read=join(answers.get("novels_read")),
        novels_dropped=join(answers.get("novels_dropped")),
        novel_categories=join(answers.get("novel_categories")),
        core_artists=join(answers.get("core_artists")),
        companion_artists=join(answers.get("companion_artists")),
        music_avoid=join(answers.get("music_avoid")),
        voice_block=voice_block,
        notes=answers.get("notes") or "（无）",
    )


def cron_plan(answers: dict) -> list:
    """按内容按排期建议；agent 照这个建 cron。"""
    plan = [
        {"name": "片单卡", "schedule": "每周日 20:00",
         "cmd": "python3 -m cards.weekly",
         "note": "番剧（Bangumi 当季）+ 网文（起点月票榜）"},
        {"name": "任天堂新作", "schedule": "每周四 20:00",
         "cmd": ("python3 sources/nintendo_hk.py --new > /tmp/nk.json"
                 " && python3 setup/poster_sheet.py --data /tmp/nk.json"
                 " && python3 -m cards.games --data /tmp/nk.json"
                 " && python3 sources/nintendo_hk.py --commit --from-payload /tmp/nk.json"),
         "steps": ["抓取 + 下载海报 + 标注 review",
                   "海报拼图给 agent 判断「是不是 AI 垃圾」，必要时删条目",
                   "发卡",
                   "记基线：只提交 payload 里真正发出去的（--commit 不再接受 --all）"],
         "note": "拆成四步更好：agent 要在第 2 步之后看一眼再发。没有新增时第 1 步输出 new_count=0，直接跳过发卡"},
    ]
    if answers.get("core_artists"):
        plan.append({"name": "音乐新发行", "schedule": "每月 1 日 10:00",
                     "cmd": "python3 -m cards.music --days 45",
                     "note": "内核层艺人的新专辑；没有新作品则静默"})
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", help="访谈结果 JSON")
    parser.add_argument("--name", default="你", help="档案里的称呼")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--example", action="store_true", help="打印答案模板")
    args = parser.parse_args()

    if args.example:
        print(json.dumps(example(), ensure_ascii=False, indent=2))
        return 0

    if not args.answers:
        parser.error("需要 --answers（或 --example 看模板）")

    answers = {**DEFAULTS, **json.loads(Path(args.answers).read_text(encoding="utf-8"))}
    name = (answers.get("name") or args.name or "").strip()
    if name in ("你", "用户"):
        name = ""       # 占位称呼不进档案：卡片标题宁可中性，也不要「你 · 本周片单」
    profile = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "name": name,
        "depth": answers["depth"],
        "lines": answers["lines"],
        "anime_watched": answers["anime_watched"],
        "anime_avoid": answers["anime_avoid"],
        "anime_hits": answers["anime_hits"],
        "novels_read": answers["novels_read"],
        "novels_dropped": answers["novels_dropped"],
        "novel_categories": answers["novel_categories"],
        "novel_authors": answers["novel_authors"],
        "core_artists": answers["core_artists"],
        "companion_artists": answers["companion_artists"],
        "music_avoid": answers["music_avoid"],
        "game_series": answers["game_series"],
        "game_hits": answers["game_hits"],
        "game_avoid": answers["game_avoid"],
        "game_caution": answers["game_caution"],
        "voice": answers["voice"],
        "notes": answers["notes"],
    }
    # 已读 / 已看不分家：网文排重要用小说名单，番剧排重要用动画名单
    profile["novels_seen"] = sorted(set(answers["novels_read"]) | set(answers["novels_dropped"]))
    profile["anime_watched_all"] = sorted(set(answers["anime_watched"]))

    md = render(answers, name or "你")
    targets = {
        "profile": config.profile_path(),
        "taste": config.home() / "taste_profile.md",
        "env": config.env_path(),
    }
    if args.dry_run:
        print("会写入：")
        for label, path in targets.items():
            print(f"  {label}: {path}")
        print("\n--- taste_profile.md 预览 ---\n")
        print(md[:1200])
        return 0

    try:
        config.ensure_writable(targets["profile"].parent)
        targets["profile"].write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        targets["taste"].write_text(md, encoding="utf-8")
        if not targets["env"].exists():
            config.save_env({"FEISHU_APP_ID": "", "FEISHU_APP_SECRET": "", "FEISHU_CHAT_ID": ""})
    except OSError as exc:
        raise SystemExit(config.hint(targets["profile"].parent, exc))

    print(f"✅ 口味档案已写入 {targets['profile']}")
    print(f"✅ 可读版 {targets['taste']}")
    print(f"✅ 凭据模板 {targets['env']}（还没填的话按 references/tokens.md 补）")
    print("\n建议排期（agent 照此建定时任务）：")
    for item in cron_plan(answers):
        print(f"  · {item['name']}｜{item['schedule']}")
        print(f"      {item['cmd']}")
        for step in item.get("steps", []):
            print(f"      - {step}")
    print("\n回写「已看 / 不想看」：python3 setup/mark.py seen anime 作品名"
          "（写进 feedback.json，下一轮筛选自动排掉；改档案不会冲掉）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
