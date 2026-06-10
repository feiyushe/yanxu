#!/usr/bin/env python3
"""yanxu (燕叙) - 微信公众号优质内容采集脚本
参考暴富羊(baofuyang) 的 fetch_rss.py 设计
- XML 解析 → 清洗 → 按 link 去重 → 写入 ../data/YYYY-MM-DD.json
- 支持质量关键词评分
"""

import html as html_mod
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

# ─── 网络请求 ─────────────────────────────────────────────

def fetch_url(url: str, timeout: int = 15, retries: int = 3) -> Optional[bytes]:
    """带重试的 HTTP GET"""
    hdrs = {"User-Agent": "Mozilla/5.0 (compatible; YanxuBot/1.0)"}
    for attempt in range(retries):
        try:
            req = Request(url, headers=hdrs)
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (URLError, TimeoutError, OSError) as e:
            if attempt < retries - 1:
                print(f"[WARN] 重试 {attempt + 1}/{retries} [{url}]: {e}", file=sys.stderr)
            else:
                print(f"[WARN] 请求失败 [{url}]: {e}", file=sys.stderr)
                return None
    return None


# ─── HTML / 日期 ─────────────────────────────────────────

def clean_html(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", "", raw)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()[:500]


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_pubdate(date_str: Optional[str]) -> str:
    """多种 pubDate 格式 → 北京时间"""
    if not date_str:
        return _now_str()
    s = date_str.strip()
    rfc = re.sub(r"\b(?:UTC|GMT)\b", "+0000", s)
    bj = timezone(timedelta(hours=8))
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(rfc, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(bj).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return _now_str()


def remove_read_count(title: str) -> str:
    """去除标题中的阅读数标签，如 '10.0万'"""
    return re.sub(r"^\d+\.?\d*万\s*", "", title).strip()


def calc_quality_score(title: str, content: str) -> int:
    """基于关键词计算质量评分（0-10分）"""
    score = 5  # 基础分
    text = title + " " + content
    for kw in config.QUALITY_KEYWORDS:
        if kw in text:
            score += 1
    return min(score, 10)


# ─── RSS 解析 ────────────────────────────────────────────

def fetch_single_rss(url: str, source: str, timeout: int = 15) -> list[dict]:
    """抓取单个 RSS 源，解析为结构化数据"""
    raw = fetch_url(url, timeout=timeout)
    if raw is None:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"[WARN] XML 解析失败 [{source}]: {e}", file=sys.stderr)
        return []

    items: list[dict] = []
    for item_el in root.iter("item"):
        title = (item_el.findtext("title") or "").strip()
        link = (item_el.findtext("link") or "").strip()
        raw_date = (item_el.findtext("pubDate") or "").strip()
        desc = (item_el.findtext("description") or "").strip()

        if not link:
            continue

        # 清洗
        if config.REMOVE_READ_COUNT_TAG:
            title = remove_read_count(title)
        if not title:
            continue

        items.append({
            "title": title,
            "link": link,
            "date": parse_pubdate(raw_date),
            "contentSnippet": clean_html(desc),
            "source": source,
            "sourceName": config.SOURCE_MAP.get(source, source),
            "qualityScore": calc_quality_score(title, desc),
        })
    return items


# ─── 筛选 ────────────────────────────────────────────────

def filter_items(items: list[dict]) -> list[dict]:
    """排除低质量/广告内容"""
    result = []
    for item in items:
        title = item["title"]
        # 排除关键词
        if any(ex in title for ex in config.EXCLUDE_TITLE):
            continue
        result.append(item)
    return result


# ─── 持久化 ──────────────────────────────────────────────

def load_day(path: Path) -> list[dict]:
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_day(path: Path, data: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def deduplicate_by_link(data: list[dict]) -> list[dict]:
    """按 link 去重，保留最后出现的"""
    seen: dict[str, dict] = {}
    for item in data:
        seen[item["link"]] = item
    return list(seen.values())


def today_file() -> Path:
    return config.DATA_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.json"


# ─── 主流程 ──────────────────────────────────────────────

def main(dry_run: bool = False) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    filepath = today_file()
    print(f"[INFO] 数据文件: {filepath}")

    existing_all = load_day(filepath)
    existing = [item for item in existing_all if item.get("date", "")[:10] == today]
    removed = len(existing_all) - len(existing)
    if removed:
        print(f"[INFO] 清理旧日期数据: {removed} 条")
    print(f"[INFO] 已有今日记录: {len(existing)} 条")

    all_new: list[dict] = []
    for source, url in config.RSS_URLS.items():
        print(f"[INFO] 抓取 {config.SOURCE_MAP.get(source, source)} ...")
        items = fetch_single_rss(url, source)
        items = filter_items(items)
        items = [item for item in items if item.get("date", "")[:10] == today]
        seen = {item["link"] for item in existing}
        added: list[dict] = []
        for item in items:
            if item["link"] not in seen:
                seen.add(item["link"])
                existing.append(item)
                added.append(item)
        all_new.extend(added)
        print(f"[INFO]   -> 新增 {len(added)}/{len(items)} 条（当日）")

    existing = deduplicate_by_link(existing)

    # 限制每天条数
    if len(existing) > config.MAX_DAILY_ITEMS:
        # 按质量评分排序，保留高分的
        existing.sort(key=lambda x: x.get("qualityScore", 0), reverse=True)
        existing = existing[:config.MAX_DAILY_ITEMS]
        print(f"[INFO] 超过上限，截断至 {config.MAX_DAILY_ITEMS} 条")

    if not dry_run:
        save_day(filepath, existing)
    print(f"[INFO] 总记录: {len(existing)} 条，本次新增: {len(all_new)} 条")

    if all_new:
        # 按质量评分排序
        all_new.sort(key=lambda x: x.get("qualityScore", 0), reverse=True)
        print("\n=== NEW_ITEMS_START ===")
        print(json.dumps(all_new, ensure_ascii=False, indent=2))
        print("=== NEW_ITEMS_END ===")

    return len(all_new)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    sys.exit(0 if main(dry_run=dry_run) >= 0 else 1)