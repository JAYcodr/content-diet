#!/usr/bin/env python3
"""飞书卡片投递工具（Card JSON 2.0）—— 发卡片 / 传图 / 回读校验。

用法：
  python3 feishu_card.py demo  --chat oc_xxx [--image /path.png]
  python3 feishu_card.py send  --chat oc_xxx --card card.json
  python3 feishu_card.py image --path /path.png          # 上传，打印 img_key
  python3 feishu_card.py read  --chat oc_xxx --limit 5   # 回读最近消息
  python3 feishu_card.py read  --message om_xxx

凭据取自 /opt/data/.env 的 FEISHU_APP_ID / FEISHU_APP_SECRET。代理走环境变量。
构建函数：card_v2 / md / table / img / cols / btn / divider / footer。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from core import config

BASE = "https://open.feishu.cn/open-apis"


# ---------------------------------------------------------------- 基础设施
def token() -> str:
    """租户 token。凭据来自环境变量或 $CONTENT_DIET_HOME/.env。"""
    app_id = config.get("FEISHU_APP_ID")
    app_secret = config.get("FEISHU_APP_SECRET")
    if not (app_id and app_secret):
        raise RuntimeError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET（见 references/tokens.md）")
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(f"{BASE}/auth/v3/tenant_access_token/internal",
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    if d.get("code"):
        raise RuntimeError(f"token failed: {d}")
    return d["tenant_access_token"]


def _api(path: str, tok: str, body: dict | None = None, method: str = "POST") -> dict:
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"code": e.code, "msg": e.read().decode()[:600]}


def upload_image(path: str) -> str:
    """上传图片取 img_key（image_type=message）。建议 ≤10MB、高宽比不超 16:9。"""
    tok = token()
    boundary = uuid.uuid4().hex
    p = Path(path)
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="image_type"\r\n\r\nmessage\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{p.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode(),
        p.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        f"{BASE}/im/v1/images", data=body, method="POST",
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    if d.get("code"):
        raise RuntimeError(f"upload failed: {d}")
    return d["data"]["image_key"]


def send_card(chat_id: str, card: dict) -> dict:
    return _api("/im/v1/messages?receive_id_type=chat_id", token(), {
        "receive_id": chat_id, "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False)})


def read_messages(chat_id: str, limit: int = 5) -> list[dict]:
    return _api(f"/im/v1/messages?container_id_type=chat&container_id={chat_id}"
                f"&page_size={limit}&sort_type=ByCreateTimeDesc", token(),
                method="GET").get("data", {}).get("items", [])


def read_message(message_id: str) -> dict:
    return _api(f"/im/v1/messages/{message_id}", token(), method="GET").get("data", {})


# ---------------------------------------------------------------- 组件 helpers
def md(content: str, *, size: str = "normal", align: str = "left", margin: str | None = None) -> dict:
    """富文本块。支持 CommonMark + 少量 HTML：<font color> <text_tag> <at> <br> <hr> <person>
    <link icon>。不支持 markdown 表格——表格必须用 table 组件。"""
    el = {"tag": "markdown", "content": content, "text_size": size, "text_align": align}
    if margin:
        el["margin"] = margin
    return el


def table(columns: list[tuple[str, str]], rows: list[list[str]], *,
          page_size: int = 10, row_height: str = "middle") -> dict:
    """columns=[(name, 显示名)]，rows=[[c1,c2,...]]。单元格装不下会在末尾截断加 …（点开看全）。
    每张卡最多 5 个 table，且只能放在 body 根节点。"""
    return {
        "tag": "table", "page_size": page_size, "row_height": row_height,
        "header_style": {"text_align": "left", "text_size": "normal",
                         "background_style": "grey", "bold": True, "lines": 1},
        "columns": [{"name": n, "display_name": d, "data_type": "text", "width": "auto"}
                    for n, d in columns],
        "rows": [dict(zip([n for n, _ in columns], row)) for row in rows],
    }


def img(img_key: str, *, alt: str = "", scale_type: str = "crop_center",
        size: str | None = None, preview: bool = True, radius: str | None = None,
        margin: str | None = None) -> dict:
    """图片。scale_type: crop_center / crop_top / fit_horizontal / stretch；size 形如 '340px 170px'。
    不给 size 会按原比例铺满卡片宽度。"""
    el = {"tag": "img", "img_key": img_key, "alt": {"tag": "plain_text", "content": alt},
          "scale_type": scale_type, "preview": preview}
    if size:
        el["size"] = size
    if radius:
        el["corner_radius"] = radius
    if margin:
        el["margin"] = margin
    return el


def cols(*columns: tuple[int, list[dict]]) -> dict:
    """并排分栏：cols((1,[el]), (2,[el]))，数字是权重。按钮必须放 column 里才会并排。"""
    return {"tag": "column_set", "flex_mode": "none", "columns": [
        {"tag": "column", "width": "weighted", "weight": w, "elements": els}
        for w, els in columns]}


def btn(label: str, *, type_: str = "default", width: str = "fill",
        url: str | None = None, size: str = "medium") -> dict:
    """按钮。type_: default/primary/danger。只能放 column/form 等容器内；
    直接放 body 根节点会变成满宽纵向堆叠。"""
    el = {"tag": "button", "type": type_, "width": width,
          "text": {"tag": "plain_text", "content": label}}
    if size != "medium":
        el["size"] = size
    if url:
        el["behaviors"] = [{"type": "open_url", "default_url": url}]
    return el


def divider() -> dict:
    return {"tag": "hr"}


def footer(content: str) -> dict:
    """灰字注脚（2.0 没有 note 组件，用 notation 字号代替）。"""
    return md(f"<font color='grey'>{content}</font>", size="notation")


def card_v2(*, title: str, subtitle: str | None = None, template: str = "indigo",
            elements: list[dict], width: str = "fill") -> dict:
    """width: fill（自适应屏宽）/ compact（400px）/ default（PC 最宽 600px）。"""
    header: dict = {"title": {"tag": "plain_text", "content": title}, "template": template}
    if subtitle:
        header["subtitle"] = {"tag": "plain_text", "content": subtitle}
    return {"schema": "2.0", "config": {"width_mode": width}, "header": header,
            "body": {"elements": elements}}


# ---------------------------------------------------------------- demo
def demo_card(img_key: str | None = None) -> dict:
    els: list[dict] = []
    if img_key:
        els.append(img(img_key, alt="示例图", scale_type="crop_center",
                       size="340px 170px", radius="8px"))
    els += [
        md("卡片比普通消息多的是**结构**：能分块、并排、放表、放图，还能带按钮。"
           "下面这张表是这套语法的边界。"),
        table([("a", "能力"), ("b", "怎么写"), ("c", "注意")],
              [["表格", "table 组件", "单元格会截断"],
               ["图片", "img 组件", "给 size 才不铺满"],
               ["按钮", "放 column 里", "根节点会满宽"],
               ["行内代码", "`code`", "黑底小块"]]),
        cols((1, [md("**能用**\n- `<font>` 上色\n- `<text_tag>` 标签\n- 代码块")]),
             (1, [md("**不能用**\n- md 表格\n- action 容器\n- 图片自适应")])),
        cols((1, [btn("主按钮", type_="primary")]), (1, [btn("次按钮")])),
        footer("生成 → 上传取 img_key → 组装 → 发送，链路已验证"),
    ]
    return card_v2(title="铃 · 卡片速查", subtitle="Card JSON 2.0 · 实测版", elements=els)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--chat", required=True)
    d.add_argument("--image")
    s = sub.add_parser("send")
    s.add_argument("--chat", required=True)
    s.add_argument("--card", required=True)
    i = sub.add_parser("image")
    i.add_argument("--path", required=True)
    r = sub.add_parser("read")
    r.add_argument("--chat")
    r.add_argument("--message")
    r.add_argument("--limit", type=int, default=5)
    a = ap.parse_args()

    if a.cmd == "image":
        print(upload_image(a.path)); return 0
    if a.cmd == "demo":
        key = upload_image(a.image) if a.image else None
        print(json.dumps(send_card(a.chat, demo_card(key)), ensure_ascii=False)[:400]); return 0
    if a.cmd == "send":
        card = json.loads(Path(a.card).read_text(encoding="utf-8"))
        print(json.dumps(send_card(a.chat, card), ensure_ascii=False)[:400]); return 0
    if a.cmd == "read":
        if a.message:
            print(json.dumps(read_message(a.message), ensure_ascii=False, indent=2)[:4000])
        else:
            for m in read_messages(a.chat, a.limit):
                print(f"{m['message_id']} | {m['msg_type']} | {m['create_time']} | "
                      f"{m.get('body', {}).get('content', '')[:300]}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
