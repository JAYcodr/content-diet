"""content-diet 的配置与路径中心。

所有状态（口味档案、缓存、锁）都放在 ``CONTENT_DIET_HOME``（默认 ``~/.content-diet``），
凭据只从环境变量或该目录下的 ``.env`` 读，不写死在代码里。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

ENV_FILE_NAME = ".env"
FEEDBACK_FILE_NAME = "feedback.json"
DEFAULT_HOME = "~/.content-diet"

# 可选代理：有些源（如 Bangumi）在部分网络下必须走代理才能访问
PROXY = os.environ.get("CONTENT_DIET_PROXY") or os.environ.get("HTTPS_PROXY") or ""


def hint(path: Path, exc: Exception) -> str:
    """写入失败的可照做提示（沙箱里 $HOME 常不可写，这是预期环境问题）。"""
    return (
        f"无法写入 {path}（{exc}）\n"
        "当前权限模式不允许写工作区外。改运行：\n"
        "  export CONTENT_DIET_HOME=$PWD/.content-diet\n"
        "或在会话里切到「完全权限」。"
    )


def home(create: bool = False) -> Path:
    """状态根目录：CONTENT_DIET_HOME → ~/.content-diet。

    默认**不建目录**——只读路径不能因为"读一下配置"就崩。真要写时用
    :func:`ensure_writable`，它会把 PermissionError 翻译成上面那句提示。
    """
    raw = os.environ.get("CONTENT_DIET_HOME", DEFAULT_HOME)
    return Path(raw).expanduser()


def ensure_writable(path: Path) -> Path:
    """目录能建 + 能写文件才放行；否则给一句可照做的提示（不是 traceback）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.touch(exist_ok=True)
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise SystemExit(hint(path, exc))
    return path


def try_mkdir(path: Path) -> bool:
    """建目录，失败返回 False（只读环境下让调用方降级，而不是抛异常）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        warn_unwritable(path, exc)
        return False


_WARNED_UNWRITABLE: set = set()


def warn_unwritable(path: Path, exc: Exception) -> None:
    """同一个目录只提示一次。

    缓存/基线写不进去可以降级，但**不能一声不响**——否则用户看到的是
    「每周都慢、封面偶尔失败、昨天推过的又推一次」，没有任何线索指向目录不可写。
    """
    key = str(path)
    if key in _WARNED_UNWRITABLE:
        return
    _WARNED_UNWRITABLE.add(key)
    print(
        f"⚠ 状态目录不可写：{path}（{exc.__class__.__name__}: {exc}）\n"
        "  缓存与排重基线降级：封面每次重下、seen / 已看回写不落地。改运行：\n"
        "  export CONTENT_DIET_HOME=$PWD/.content-diet\n"
        "  或让 doctor 报一次：python3 setup/doctor.py",
        file=sys.stderr,
    )


def can_write(path: Path) -> bool:
    """这个目录能不能写（doctor 用它做能力探测）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


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


def state_dir(name: str = "", *, quiet: bool = False) -> Path:
    """缓存/状态目录：尽量建，建不了也返回路径——只读环境下降级，不崩。

    但降级要留话：失败时打一次 stderr 提示（``quiet=True`` 由调用方自己负责说明）。
    """
    path = home() / name if name else home()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if not quiet:
            warn_unwritable(path, exc)
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


def display_name() -> str:
    """卡片标题用的称呼。没档案或没填就返回空串——标题退化成中性，绝不硬编码人名。"""
    profile = loading_profile() or {}
    return str(profile.get("name") or "").strip()


# ---------------------------------------------------------------- 反馈回写（已看 / 不想看）
# 存在 profile.json 旁边，不污染访谈档案：档案是「他说的」，feedback 是「用出来的」。
def feedback_path() -> Path:
    return home() / FEEDBACK_FILE_NAME


def load_feedback() -> dict:
    """{'anime': {'seen': [...], 'skip': [...]}, 'novel': {...}, 'album': {...}}"""
    path = feedback_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def feedback_list(category: str, kind: str) -> List[str]:
    """某一类的已看 / 不想看名单（kind: seen / skip）。缺失返回空列表。"""
    bucket = (load_feedback().get(category) or {})
    if not isinstance(bucket, dict):
        return []
    return [str(x).strip() for x in (bucket.get(kind) or []) if str(x).strip()]


def feedback_excludes(category: str) -> List[str]:
    """排重用的合并名单：已看 ∪ 不想看。"""
    return feedback_list(category, "seen") + feedback_list(category, "skip")


def save_feedback(data: dict) -> Path:
    path = ensure_writable(home()) / FEEDBACK_FILE_NAME
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def save_env(values: Dict[str, str]) -> Path:
    """把若干键写入 .env（已存在的键会被覆盖），返回路径。"""
    path = env_path()
    ensure_writable(path.parent)      # 探测的是目录；.env 是文件，别当目录建
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
