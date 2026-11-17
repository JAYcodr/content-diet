#!/usr/bin/env python3
"""从已有的 DSH 飞书通道插件（``@xmanrui/dsh-im``）里复用机器人凭据，免得再建第二个应用。

按 issue #4：很多人已经装好 dsh-im（建应用 / 扫码授权 / 权限 / 长连接 / chat_id 全做完了），
再让用户去 open.feishu.cn 建第二个应用纯属重复劳动。

真实结构（dsh-im 0.1.x 实测，2026-11）::

    ~/.dsh/integrations/dsh-feishu/config.json
        {"version": 2,
         "bots": [{"id": "bot_…", "appId": "cli_…",
                   "secretRef": "DSH_FEISHU_APP_SECRET_…",   # 只是键名，不是密钥本身
                   "botName": "…", "domain": "feishu", "activated": 2, …}]}

    ~/.dsh/.credentials.yaml
        refs:
          DSH_FEISHU_APP_SECRET_…: <32 位 app secret>          # secretRef 指向这里
          XIAOMI_API_KEY: …                                   # 别人的密钥，别碰

``secretRef`` 只是 ``refs:`` 里的键名；按位置取 refs 的第一条会拿到别的服务的密钥。

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
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config  # noqa: E402

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

APP_ID_FIELDS = ("appId", "app_id", "appID")
SECRET_REF_FIELDS = ("secretRef", "secret_ref", "appSecretRef")


def first_existing(key: str) -> Optional[Path]:
    for path in CANDIDATES[key]:
        if path.exists():
            return path
    return None


def _pick(mapping: Dict[str, Any], fields: Tuple[str, ...]) -> str:
    for field in fields:
        value = mapping.get(field)
        if value:
            return str(value).strip()
    return ""


def read_bots(config_path: Path) -> List[Dict[str, str]]:
    """从 integration 配置里取出 bot 列表（新格式 bots[] / 旧格式顶层字段）。"""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"读不到 {config_path}：{exc}", file=sys.stderr)
        return []
    if not isinstance(data, dict):
        return []

    bots: List[Dict[str, str]] = []
    raw_bots = data.get("bots")
    if isinstance(raw_bots, list):
        for item in raw_bots:
            if not isinstance(item, dict):
                continue
            app_id = _pick(item, APP_ID_FIELDS)
            secret_ref = _pick(item, SECRET_REF_FIELDS)
            if not app_id and not secret_ref:
                continue
            bots.append({
                "appId": app_id,
                "secretRef": secret_ref,
                "botName": str(item.get("botName") or item.get("name") or "").strip(),
                "domain": str(item.get("domain") or "").strip(),
                "activated": str(item.get("activated") or ""),
            })

    if not bots:
        # 旧格式：appId 在顶层，或嵌在 feishu/config/settings 里
        app_id = _pick(data, APP_ID_FIELDS)
        secret_ref = _pick(data, SECRET_REF_FIELDS)
        if not app_id:
            for key in ("feishu", "config", "settings", "lark"):
                sub = data.get(key)
                if isinstance(sub, dict):
                    app_id = _pick(sub, APP_ID_FIELDS)
                    secret_ref = secret_ref or _pick(sub, SECRET_REF_FIELDS)
                    if app_id:
                        break
        if app_id:
            bots.append({"appId": app_id, "secretRef": secret_ref,
                         "botName": "", "domain": "", "activated": ""})
    return bots


def pick_bot(bots: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """有多个 bot 时优先挑能用的：带 secretRef 优先，其次 activated 非 0。"""
    usable = [b for b in bots if b["appId"] and b["secretRef"]]
    pool = usable or bots
    for bot in pool:
        if bot["activated"] not in ("", "0", "false", "False"):
            return bot
    return pool[0] if pool else None


def _parse_refs_fallback(text: str) -> Dict[str, str]:
    """没装 PyYAML 时的最小解析：只取 ``refs:`` 下一层 ``key: value``。"""
    refs: Dict[str, str] = {}
    refs_indent: Optional[int] = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if refs_indent is None:
            if line.strip() == "refs:":
                refs_indent = indent
            continue
        if indent <= refs_indent:
            break
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        value = value.strip().strip("'\"")
        if key.strip() and value:
            refs[key.strip()] = value
    return refs


def read_refs(cred_path: Path) -> Dict[str, str]:
    """读 ``.credentials.yaml`` 的 ``refs:`` 映射（键名 → 密钥）。"""
    text = cred_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ImportError:
        return _parse_refs_fallback(text)
    try:
        data = yaml.safe_load(text) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"读不到 {cred_path}：{exc}", file=sys.stderr)
        return _parse_refs_fallback(text)
    refs = data.get("refs") if isinstance(data, dict) else None
    if not isinstance(refs, dict):
        return {}
    return {str(k): str(v).strip().strip("'\"") for k, v in refs.items() if v}


def resolve_secret(refs: Dict[str, str], secret_ref: str) -> Tuple[str, str]:
    """按 secretRef 取密钥；退回同名前缀匹配。返回 (secret, 说明)。"""
    if secret_ref and refs.get(secret_ref):
        return refs[secret_ref], f"refs[{secret_ref}]"
    if secret_ref:
        suffix = secret_ref.rsplit("_", 1)[-1].lower()
        for key, value in refs.items():
            if suffix and key.lower().endswith(suffix):
                return value, f"refs[{key}]（按后缀匹配）"
    feishu_keys = [k for k in refs if "FEISHU" in k.upper() and "SECRET" in k.upper()]
    if len(feishu_keys) == 1:
        return refs[feishu_keys[0]], f"refs[{feishu_keys[0]}]（唯一飞书密钥）"
    if len(feishu_keys) > 1:
        print(f"refs 里有 {len(feishu_keys)} 个飞书密钥，无法确定用哪个：" + ", ".join(feishu_keys),
              file=sys.stderr)
    return "", ""


def mask(secret: str) -> str:
    """只给首尾各 4 位：能对上是哪一把，但截图/日志里不落全量密钥。"""
    if len(secret) <= 8:
        return f"{'*' * len(secret)}（{len(secret)} 字符）"
    return f"{secret[:4]}…{secret[-4:]}（{len(secret)} 字符）"


def verify(app_id: str, secret: str) -> Tuple[bool, str]:
    """用这套凭据换一次 tenant_access_token——换得到才说明 secret 真是飞书的。"""
    import os

    saved = (os.environ.get("FEISHU_APP_ID"), os.environ.get("FEISHU_APP_SECRET"))
    os.environ["FEISHU_APP_ID"], os.environ["FEISHU_APP_SECRET"] = app_id, secret
    try:
        from core.feishu import token
        token()
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:300]
    finally:
        for key, value in zip(("FEISHU_APP_ID", "FEISHU_APP_SECRET"), saved):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def sanity_check(app_id: str, secret: str) -> str:
    """写 .env 之前的最后一道闸：拿错键的形态有两种，都在这里挡掉。

    - secret 和 appId 一模一样：说明按位置取到了 app_id 那个键（老毛病）。
    - secret 明显太短：飞书 app secret 是 32 字符，短的大概率是别的服务的 key。
    返回空串表示通过，否则返回人话原因。
    """
    if secret and app_id and secret.strip() == app_id.strip():
        return ("读到的 secret 和 appId 一模一样——取到了错的键。不写 .env，"
                "先看 config.json 里 secretRef 指向哪个键。")
    if secret and len(secret) < 20:
        return (f"secret 只有 {len(secret)} 字符，不像飞书 app secret（32 字符）。"
                "不写 .env：写进去只会让第一次发卡 4xx，比现在更难查。")
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只看读到什么，不写 .env")
    parser.add_argument("--verify", action="store_true",
                        help="换一次 tenant_access_token，证明 secret 真的可用")
    args = parser.parse_args()

    config_path = first_existing("integration_config")
    cred_path = first_existing("credentials")

    if not config_path and not cred_path:
        print("没找到 DSH 飞书通道插件的配置。两个选择：")
        print("  1. 按 references/tokens.md 手动建一个企业自建应用（3 个权限 + 发版本）；")
        print("  2. 在 DSH 里装好 @xmanrui/dsh-im 后再回来跑这个脚本。")
        return 0

    bots = read_bots(config_path) if config_path else []
    bot = pick_bot(bots)
    refs = read_refs(cred_path) if cred_path else {}

    app_id = bot["appId"] if bot else ""
    secret_ref = bot["secretRef"] if bot else ""
    secret, how = resolve_secret(refs, secret_ref) if secret_ref else ("", "")
    if not secret and not secret_ref:
        # 配置里没给 secretRef：只接受唯一一个「飞书 secret」键，多一个都不猜
        secret, how = resolve_secret(refs, "")

    print(f"integration 配置：{config_path or '（未找到）'}")
    print(f"凭据文件：{cred_path or '（未找到）'}")
    if len(bots) > 1:
        print(f"发现 {len(bots)} 个机器人，选用第一个可用的：")
        for item in bots:
            mark = " ←" if item is bot else ""
            print(f"  · {item['botName'] or '(未命名)'} {item['appId']} activated={item['activated'] or '-'}{mark}")
    print(f"appId：{app_id or '（没读到，字段名可能不同）'}")
    if secret:
        print(f"secret：{mask(secret)}　来源 {how}")
    elif secret_ref:
        print(f"secret：（secretRef = {secret_ref}，但在 refs 里没找到对应密钥）")
    else:
        print("secret：（没读到，检查 refs: 结构）")

    problem = sanity_check(app_id, secret)
    if problem:
        print(f"\n✗ {problem}", file=sys.stderr)
        return 1

    if args.verify:
        if not (app_id and secret):
            print("\n✗ appId / secret 没读全，没法验证。")
            return 1
        ok, detail = verify(app_id, secret)
        print("✓ 凭据可用：已换到 tenant_access_token" if ok else f"✗ 凭据无效：{detail}")
        if not ok:
            return 1

    if args.dry_run:
        if app_id and secret:
            print("\n--dry-run：没有写 .env（凭据看起来没问题，去掉 --dry-run 就落盘）。")
            return 0
        print("\n--dry-run：还没读全，先别写。")
        return 1
    if not (app_id and secret):
        print("\n没读全，先不写 .env。手动填进 references/tokens.md 里那三项即可。")
        return 1

    config.save_env({"FEISHU_APP_ID": app_id, "FEISHU_APP_SECRET": secret})
    print(f"\n已写入 {config.env_path()}（只写了 appId/secret，chat_id 还要你选）")
    print("下一步：把机器人拉进群/发一条私聊，然后 `python3 setup/feishu_chats.py` 列出会话拿 chat_id。")
    print("再跑 `python3 setup/doctor.py --send-test` 确认手机真收到。")
    print("注意：发消息不需要长连接，不会和 dsh-im 抢事件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
