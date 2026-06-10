#!/usr/bin/env python3
"""
gzh 素材库检索工具
用途：Agent 调用的检索工具，按条件查找文章、素材、图片

用法：
  python3 search.py --query 不锈钢
  python3 search.py --tag 生活杂谈
  python3 search.py --type article --date 2026-06
  python3 search.py --type image
  python3 search.py --all          # 显示所有条目
  python3 search.py --recent       # 最近5篇文章
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_FILE = BASE_DIR / "index.json"


def load_index() -> dict:
    if INDEX_FILE.exists():
        with open(INDEX_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"articles": [], "images": [], "references": []}


def search_text(query: str, files: list) -> list[dict]:
    """使用 ripgrep 搜索文本内容"""
    results = []
    for f in files:
        path = f["path"]
        try:
            r = subprocess.run(
                ["rg", "-l", "-i", query, str(BASE_DIR / path)],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0:
                results.append(f)
        except Exception:
            continue
    return results


def main():
    parser = argparse.ArgumentParser(description="gzh 素材库检索")
    parser.add_argument("--query", help="全文搜索关键词")
    parser.add_argument("--tag", help="按标签搜索")
    parser.add_argument("--type", choices=["article", "image", "reference", "all"])
    parser.add_argument("--date", help="按日期筛选（前缀匹配，如 2026-06）")
    parser.add_argument("--all", action="store_true", help="显示全部")
    parser.add_argument("--recent", action="store_true", help="最近5篇文章")
    args = parser.parse_args()

    index = load_index()

    # 收集所有条目
    all_items = []
    for entry in index.get("articles", []):
        entry["_type"] = "article"
        all_items.append(entry)
    for entry in index.get("images", []):
        entry["_type"] = "image"
        all_items.append(entry)
    for entry in index.get("references", []):
        entry["_type"] = "reference"
        all_items.append(entry)

    results = all_items

    # 筛选：类型
    if args.type and args.type != "all":
        results = [r for r in results if r["_type"] == args.type]

    # 筛选：日期
    if args.date:
        results = [r for r in results if r.get("date", "").startswith(args.date)]

    # 筛选：标签
    if args.tag:
        results = [r for r in results if args.tag in r.get("tags", [])]

    # 全文搜索
    if args.query:
        # 先按文件名/标题匹配
        keyword = args.query.lower()
        text_hits = [r for r in results if keyword in r.get("title", "").lower()
                      or keyword in r.get("filename", "").lower()]
        # 再按内容匹配
        file_hits = search_text(args.query, results)
        file_paths = {h["path"] for h in file_hits}
        # 合并
        seen = set()
        combined = text_hits + [h for h in file_hits if h["path"] not in seen]
        for h in text_hits:
            seen.add(h["path"])
        results = combined

    # 最近5篇
    if args.recent:
        articles = [r for r in all_items if r["_type"] == "article"]
        articles.sort(key=lambda x: x.get("date", ""), reverse=True)
        results = articles[:5]

    # 输出
    if not results:
        print(json.dumps({"count": 0, "results": []}, ensure_ascii=False, indent=2))
        return

    output = []
    for r in results:
        entry = {
            "type": r["_type"],
            "title": r.get("title", ""),
            "date": r.get("date", ""),
            "tags": r.get("tags", []),
            "path": r.get("path", ""),
        }
        if r["_type"] == "image":
            entry["prompt"] = r.get("prompt", "")
        output.append(entry)

    print(json.dumps({
        "count": len(output),
        "results": output
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
