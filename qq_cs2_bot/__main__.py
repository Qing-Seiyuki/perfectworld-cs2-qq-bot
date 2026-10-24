from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import URLError

from .provider import fetch_detail
from .report import render_report


def main() -> None:
    parser = argparse.ArgumentParser(description="完美 CS2 五人文字战报（尚未连接 QQ）")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--match-id", help="单次查询真实比赛")
    source.add_argument("--input", type=Path, help="读取本地 JSON，不联网")
    parser.add_argument("--steam-id", required=True, help="用于识别我方队伍")
    parser.add_argument("--rating", choices=("rating", "pwRating"), default="pwRating")
    parser.add_argument("--save-json", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        response = (json.loads(args.input.read_text(encoding="utf-8-sig"))
                    if args.input else fetch_detail(args.match_id))
        if not isinstance(response, dict):
            raise ValueError("输入必须是 JSON 对象")
        report = render_report(response, args.steam_id, rating_field=args.rating)
        if args.save_json:
            args.save_json.parent.mkdir(parents=True, exist_ok=True)
            args.save_json.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report + "\n", encoding="utf-8")
        print(report)
    except (OSError, ValueError, URLError) as error:
        parser.exit(1, f"无法生成战报：{error}\n")


if __name__ == "__main__":
    main()
