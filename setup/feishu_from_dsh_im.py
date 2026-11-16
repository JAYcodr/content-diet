#!/usr/bin/env python3
"""从已有的 DSH 飞书通道插件（``@xmanrui/dsh-im``）里复用机器人凭据，免得再建第二个应用。

按 issue #4：很多人已经装好 dsh-im（建应用 / 扫码授权 / 权限 / 长连接 / chat_id 全做完了），
再让用户去 open.feishu.cn 建第二个应用纯属重复劳动。

用法::

    python3 setup/feishu_from_dsh_im.py           # 读 DSH 配置 → 写 .env → 列出会话
    python3 setup/feishu_from_dsh_im.py --dry-run  # 只看会读到什么，不写

找不到 DSH 配置时**不报错**，只打印"手动配置"的两行说明——DSH 用户可能根本没装插件。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402

# DSH 侧的约定路径（issue #4 里给的实测路径），逐个尝试
DSH_HOME = Path.home() / ".dsh"
CANDIDATES = {
    "integration_config": [
        DSH_HOME / "integrations" / "dsh-feishu" / "config.json",
        DSH_HOME / "integrations" / "feishu" / "config.json",
    ],
    "credentials": [
        DSH_HOME / ".credentials.yaml",
        DSH_HOME / "credentials.yaml",
    ],
}


def first_existing(key: str) -> Path | None:
    for path in CANDIDATES[key]:
        if path.exists():
            return path
    return None


def read_app_id(config_path: Path) -> str:
    """从 integration 配置里取 appId（字段名可能是 appId / app_id / appID）。"""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"读不到 {config_path}：{exc}", file=sys.stderr)
        return ""
    for key in ("appId", "app_id", "appID"):
        if isinstance(data, dict) and data.get(key):
            return str(data[key]).strip()
    # 有些配置把飞书配置整块嵌在 feishu 字段里
    for key in ("feishu", "config", "settings"):
        sub = data.get(key) if isinstance(data, dict) else None
        if isinstance(sub, dict):
            for field in ("appId", "app_id", "appID"):
                if sub.get(field):
                    return str(sub[field]).strip()
    return ""


def read_secret(cred_path: Path) -> str:
    """从 .credentials.yaml 取 secret（结构：refs.<secretRef> → 真值）。"""
    try:
        import yaml  # type: ignore
    except ImportError:
        # 没装 PyYAML 时用最小解析：只找 refs: 下的 key: value
        text = cred_path.read_text(encoding="utf-8")
        in_refs = False
        for line in text.splitlines():
            if line.strip().startswith("refs:"):
                in_refs = True
                continue
            if in_refs and ":" in line and not line.startswith((" ", "\t")):
                break
            if in_refs and ":" in line:
                _, _, value = line.partition(":")
                value = value.strip().strip("'\"")
                if value:
                    return value
        return ""
    try:
        data = yaml.safe_load(cred_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"读不到 {cred_path}：{exc}", file=sys.stderr)
        return ""
    refs = data.get("refs") or {}
    if isinstance(refs, dict):
        for value in refs.values():
            if isinstance(value, str) and value.strip():
                return value.strip().strip("'\"")
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config_path = first_existing("integration_config")
    cred_path = first_existing("credentials")

    if not config_path and not cred_path:
        print("没找到 DSH 飞书通道插件的配置。两个选择：")
        print("  1. 按 references/tokens.md 手动建一个企业自建应用（3 个权限 + 发版本）；")
        print("  2. 在 DSH 里装好 @xmanrui/dsh-im 后再回来跑这个脚本。")
        return 0

    app_id = read_app_id(config_path) if config_path else ""
    secret = read_secret(cred_path) if cred_path else ""

    print(f"integration 配置：{config_path or '（未找到）'}")
    print(f"凭据文件：{cred_path or '（未找到）'}")
    print(f"appId：{app_id or '（没读到，字段名可能不同）'}")
    print(f"secret：{'已读到' if secret else '（没读到，检查 refs: 结构）'}")

    if args.dry_run:
        return 0
    if not (app_id and secret):
        print("\n没读全，先不写 .env。手动填进 references/tokens.md 里那三项即可。")
        return 1

    config.save_env({"FEISHU_APP_ID": app_id, "FEISHU_APP_SECRET": secret})
    print(f"\n已写入 {config.env_path()}（只写了 appId/secret，chat_id 还要你选）")
    print("下一步：把机器人拉进群/发一条私聊，然后 `python3 setup/feishu_chats.py` 列出会话拿 chat_id。")
    print("注意：发消息不需要长连接，不会和 dsh-im 抢事件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
