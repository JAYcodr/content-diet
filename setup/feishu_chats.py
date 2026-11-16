#!/usr/bin/env python3
"""列出机器人所在的飞书会话（拿 FEISHU_CHAT_ID 用）。

需要权限 ``im:chat:readonly``（在 references/tokens.md 里有说明）。

用法::

    python3 setup/feishu_chats.py
    python3 setup/feishu_chats.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402
from core import feishu  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    if not config.get("FEISHU_APP_ID") or not config.get("FEISHU_APP_SECRET"):
        raise SystemExit("先配置 FEISHU_APP_ID / FEISHU_APP_SECRET（见 references/tokens.md）")

    result = feishu._api(f"/im/v1/chats?page_size={args.limit}", feishu.token(), method="GET")
    if result.get("code"):
        print(f"查询失败：{result}", file=sys.stderr)
        print("提示：确认已开通 im:chat:readonly 权限并发布版本。", file=sys.stderr)
        return 2
    items = (result.get("data") or {}).get("items") or []
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    if not items:
        print("机器人在任何会话里都没有——先把它拉进群，或给它发一条私聊消息。")
        return 0
    for chat in items:
        print(f"{chat.get('chat_id')}  {chat.get('name') or '(私聊/未命名)'}  {chat.get('chat_mode','')}")
    print("\n把要投递的那个填进 .env 的 FEISHU_CHAT_ID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
