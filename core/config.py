"""content-diet 的配置与路径中心。

所有状态（口味档案、缓存、锁）都放在 ``CONTENT_DIET_HOME``（默认 ``~/.content-diet``），
凭据只从环境变量或该目录下的 ``.env`` 读，不写死在代码里。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Optional

ENV_FILE_NAME = ".env"
DEFAULT_HOME = "~/.content-diet"

# 可选代理：有些源（如 Bangumi）在部分网络下必须走代理才能访问
PROXY = os.environ.get("CONTENT_DIET_PROXY") or os.environ.get("HTTPS_PROXY") or ""


def home() -> Path:
    """状态根目录：CONTENT_DIET_HOME → ~/.content-diet。"""
    raw = os.environ.get("CONTENT_DIET_HOME", DEFAULT_HOME)
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def env_path() -> Path:
    return home() / ENV_FILE_NAME


def load_env(force: bool = False) -> Dict[str, str]:
    """读 ``$CONTENT_DIET_HOME/.env``，不覆盖已存在的进程环境变量。"""
    cache_attr = "_content_diet_env_cache"
    if not force and getattr(load_env, cache_attr, None) is not None:
        return getattr(load_env, cache_attr)
    values: Dict[str, str] = {}
    path = env_path()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    setattr(load_env, cache_attr, values)
    return values


def get(key: str, default: str = "") -> str:
    """环境变量优先，其次 .env。"""
    value = os.environ.get(key, "").strip()
    if value:
        return value
    return (load_env().get(key) or default).strip()


def require(key: str, hint: str = "") -> str:
    value = get(key)
    if not value:
        raise SystemExit(
            f"缺少 {key}" + (f"：{hint}" if hint else "")
            + f"\n请在 {env_path()} 里补齐，或运行 `python3 setup/doctor.py` 看还差什么。"
        )
    return value


def state_dir(name: str = "") -> Path:
    path = home() / name if name else home()
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_path() -> Path:
    return home() / "profile.json"


def loading_profile() -> Optional[dict]:
    """口味档案（由 setup/init.py 生成）。没有就返回 None。"""
    import json

    path = profile_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def profile_list(key: str) -> list:
    """取档案里的某个列表字段，缺失时返回空列表。"""
    profile = loading_profile() or {}
    value = profile.get(key)
    return value if isinstance(value, list) else []


def save_env(values: Dict[str, str]) -> Path:
    """把若干键写入 .env（已存在的键会被覆盖），返回路径。"""
    path = env_path()
    existing: Dict[str, str] = {}
    order: list = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                existing[key.strip()] = value.strip()
                order.append(key.strip())
            else:
                order.append(line)
    # 保留注释行顺序，更新/追加键值
    out_lines: list = []
    written = set()
    for entry in order:
        if entry in existing:
            key = entry
            value = values.get(key, existing.get(key, ""))
            out_lines.append(f"{key}={value}")
            if key in values:
                written.add(key)
        else:
            out_lines.append(entry)
    for key, value in values.items():
        if key not in written and key not in existing:
            out_lines.append(f"{key}={value}")
    path.write_text("\n".join(out_lines).strip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    load_env(force=True)
    return path


def feishu_creds() -> tuple:
    return get("FEISHU_APP_ID"), get("FEISHU_APP_SECRET")


def feishu_chat() -> str:
    return get("FEISHU_CHAT_ID")


def has_feishu() -> bool:
    app_id, secret = feishu_creds()
    return bool(app_id and secret and feishu_chat())


def token_status() -> Dict[str, bool]:
    """各可选凭据是否就位——doctor 与降级提示共用。"""
    return {
        "feishu": has_feishu(),
        "bangumi": bool(get("BGM_API_TOKEN")),
        "qidian_cookie": bool(get("QIDIAN_COOKIE")),
        "netease_cookie": bool(get("NETEASE_COOKIE")),
    }


def hosts_from_url(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else url
