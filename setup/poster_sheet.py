#!/usr/bin/env python3
"""把待审海报拼成一张对比图，供 agent 一次看完再判断「AI 垃圾」。

用法::

    python3 poster_sheet.py --data /tmp/nk.json --out /tmp/sheet.jpg --only review

--data 是 nintendo_hk.py 输出的 JSON；只取带 poster_file 的条目。
输出顺序与屏幕上的编号一致（左上到右下），并在每个格子上印编号。
"""

from __future__ import annotations

import argparse
import json
import sys
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from core import config

TILE = (360, 203)


def build(items: List[Dict[str, Any]], out_path: str, cols: int = 4) -> List[Dict[str, Any]]:
    usable = [i for i in items if i.get("poster_file") and Path(i["poster_file"]).exists()]
    if not usable:
        raise SystemExit("没有可用的海报文件")
    tiles = []
    for index, item in enumerate(usable, 1):
        canvas = Image.new("RGB", TILE, "black")
        poster = Image.open(item["poster_file"]).convert("RGB")
        poster.thumbnail(TILE)
        canvas.paste(poster, ((TILE[0] - poster.width) // 2, (TILE[1] - poster.height) // 2))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle([0, 0, 30, 22], fill="red")
        draw.text((9, 6), str(index), fill="white")
        tiles.append(canvas)
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * TILE[0], rows * TILE[1]), "black")
    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % cols) * TILE[0], (index // cols) * TILE[1]))
    sheet.save(out_path, quality=88)
    return [{"n": n, "id": i["id"], "title": i["title"], "publisher": i["publisher"]}
            for n, i in enumerate(usable, 1)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--only", default="review", choices=["review", "all"])
    parser.add_argument("--cols", type=int, default=4)
    args = parser.parse_args()

    payload = json.loads(Path(args.data).read_text(encoding="utf-8"))
    items = payload.get("items") or payload.get("games") or []
    if args.only == "review" and payload.get("items"):
        items = [i for i in items if i.get("verdict") in ("review", "keep")]
    out_path = args.out or str(config.state_dir("nintendo") / "sheet.jpg")
    mapping = build(items, out_path, args.cols)
    print(json.dumps({"sheet": out_path, "index": mapping}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
