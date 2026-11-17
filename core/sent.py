#!/usr/bin/env python3
"""周期卡去重：同一周期、同一份内容只真发一次。

为什么需要：DSH / cron 补跑、手动重跑、agent 重试都会让同一张卡重复落到群里。
判定用「周期键 + 内容指纹」两条都相同才算重复——同周期内容变了（比如临时补了一条）
仍然允许再发，用户不会因为去重而漏掉更新。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from core import config

FILE_NAME = "sent.json"
CST = timezone(timedelta(hours=8))


def path() -> Path:
    return config.home() / FILE_NAME


def fingerprint(*parts: object) -> str:
    """内容指纹：把标题/条目/卡片正文丢进来，稳定序列化后取 sha256 前 16 位。"""
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load() -> dict:
    p = path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def week_key(prefix: str, now: Optional[datetime] = None) -> str:
    """ISO 周键：weekly-2026-W47。跨年按 ISO 年算，不会在元旦把上下两周合并。"""
    now = now or datetime.now(CST)
    year, week, _ = now.isocalendar()
    return f"{prefix}-{year}-W{week:02d}"


def month_key(prefix: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(CST)
    return f"{prefix}-{now.year}-{now.month:02d}"


def already_sent(key: str, digest: str) -> Optional[str]:
    """这个周期发过同一份内容吗？发过返回 message_id，没发过返回 None。"""
    record = load().get(key) or {}
    if record.get("fp") == digest and record.get("message_id"):
        return str(record["message_id"])
    return None


def mark_sent(key: str, digest: str, message_id: str) -> Optional[Path]:
    """记下已发。状态目录不可写时返回 None（去重失效但不影响这次发送）。"""
    if not config.try_mkdir(config.home()):
        return None
    data = load()
    data[key] = {
        "fp": digest,
        "message_id": message_id,
        "at": datetime.now(CST).isoformat(timespec="seconds"),
    }
    p = path()
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
    except OSError as exc:  # noqa: BLE001
        config.warn_unwritable(p, exc)
        return None
    return p
