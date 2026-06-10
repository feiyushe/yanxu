#!/usr/bin/env python3
"""
yanxu (言叙) - 素材采集脚本
流程优化：先微信热榜 → 再微博热搜
1. 微信热榜：读取 yanxu/data/ 每日数据，当天数据不存在则调用 fetch.py 采集
2. 微博热搜：通过 mcporter 获取实时热搜
3. 聚合输出结构化素材（给 cron agent 用）

用法: uv run --with trafilatura --script prepare_material.py
      uv run --with trafilatura --script prepare_material.py --fetch-only
      uv run --with trafilatura --script prepare_material.py --no-weibo
"""

import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ─── 路径 ────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
DATA_DIR = BASE_DIR / "data"


# ─── 1. 微信热榜采集 ─────────────────────────────────

def ensure_wechat_data() -> bool:
    """确保当天微信热榜数据存在，不存在则调 fetch.py"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_file = DATA_DIR / f"{today_str}.json"

    if today_file.exists():
        size = today_file.stat().st_size
        if size > 100:  # 非空文件
            print(f"[INFO] 微信热榜 {today_str} 数据已存在，跳过采集", file=sys.stderr)
            return True

    # 调 fetch.py 采集
    print(f"[INFO] 微信热榜 {today_str} 数据不存在或过小，正在采集...", file=sys.stderr)
    fetch_path = SCRIPT_DIR / "fetch.py"
    if not fetch_path.exists():
        print(f"[WARN] fetch.py 不存在: {fetch_path}", file=sys.stderr)
        return False

    try:
        result = subprocess.run(
            ["uv", "run", "--script", str(fetch_path)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and today_file.exists():
            print(f"[INFO] 微信热榜采集成功: {today_file} ({today_file.stat().st_size}B)", file=sys.stderr)
            return True
        else:
            print(f"[WARN] fetch.py 返回码 {result.returncode}", file=sys.stderr)
            print(f"[WARN] stderr: {result.stderr[:300]}", file=sys.stderr)
            # fallback: 读昨天数据
            return False
    except subprocess.TimeoutExpired:
        print("[WARN] fetch.py 超时（120s）", file=sys.stderr)
        return False


def load_wechat_hotlist(days: int = 2) -> list[dict]:
    """读取最近 N 天的微信热榜数据"""
    all_items = []
    today = datetime.now()

    for offset in range(days):
        day = today - timedelta(days=offset)
        filepath = DATA_DIR / f"{day.strftime('%Y-%m-%d')}.json"
        if filepath.exists():
            try:
                with open(filepath, encoding="utf-8") as f:
                    items = json.load(f)
                for item in items:
                    item["_day"] = day.strftime("%Y-%m-%d")
                all_items.extend(items)
                print(f"[INFO] 微信热榜 {day.strftime('%Y-%m-%d')}: {len(items)} 条", file=sys.stderr)
            except Exception as e:
                print(f"[WARN] 读取 {filepath} 失败: {e}", file=sys.stderr)
        else:
            print(f"[INFO] 微信热榜 {day.strftime('%Y-%m-%d')}: 文件不存在", file=sys.stderr)

    return all_items


# ─── 2. 文章全文下载（写前风格参考） ────────────────

_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"


def _fetch_html(url: str, timeout: int = 20) -> str | None:
    """用 urllib 下载 HTML 页面"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] 请求失败 [{url[:60]}]: {e}", file=sys.stderr)
        return None


def _extract_meta(html_text: str, prop: str) -> str:
    """从 HTML 提取 meta 标签 content"""
    m = re.search(rf'<meta\s+(?:property|name)="{re.escape(prop)}"\s+content="([^"]*)"', html_text)
    if m:
        return html.unescape(m.group(1)).strip()
    return ""


def download_full_article(link: str, timeout: int = 20, snippet: str = "") -> str:
    """用 trafilatura 下载文章全文（通用，不限域名）

    策略:
      1. trafilatura 主内容提取
      2. 失败则 fallback og:title + og:description
      3. 再失败则用 RSS snippet
    """
    if not link:
        return ""

    page_html = _fetch_html(link, timeout)
    if page_html is None:
        # 网络不通 → 用 RSS snippet
        return snippet[:3000] if snippet else ""

    # ── 策略1: trafilatura ──
    try:
        import trafilatura
        body = trafilatura.extract(
            page_html,
            url=link,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if body and len(body) > 100:
            title = _extract_meta(page_html, "og:title") or ""

            # 从 trafilatura 结果取首行作为标题辅助
            first_line = body.split("\n", 1)[0].strip().strip("#").strip()
            if not title:
                title = first_line[:80]

            body_trimmed = body[:3000]
            return f"# {title}\n\n{body_trimmed}" if title else body_trimmed
    except ImportError:
        print("  [WARN] trafilatura 未安装，使用 fallback", file=sys.stderr)
    except Exception as e:
        print(f"  [WARN] trafilatura 提取异常: {e}", file=sys.stderr)

    # ── 策略2: meta fallback ──
    title = _extract_meta(page_html, "og:title")
    desc = _extract_meta(page_html, "og:description")
    if title and desc:
        return f"# {title}\n\n{desc}"

    # ── 策略3: RSS snippet 兜底 ──
    if snippet:
        return snippet[:3000]
    return ""


def _load_index_json() -> tuple[list[dict], set[str]]:
    """读取 index.json 返回 (existing_refs, existing_links_set)"""
    idx_path = BASE_DIR / "index.json"
    if idx_path.exists():
        try:
            data = json.loads(idx_path.read_text(encoding="utf-8"))
            refs = data.get("references", [])
            links = {r.get("link", "") for r in refs if r.get("link")}
            return refs, links
        except Exception:
            pass
    return [], set()


def _append_index_json(new_refs: list[dict]) -> None:
    """追加新参考条目到 index.json（按 link 去重）"""
    idx_path = BASE_DIR / "index.json"
    data: dict = {"articles": [], "images": [], "references": []}
    if idx_path.exists():
        try:
            data = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing_links = {r.get("link", "") for r in data.get("references", []) if r.get("link")}
    for ref in new_refs:
        if ref["link"] not in existing_links:
            data["references"].append(ref)
            existing_links.add(ref["link"])
    idx_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def download_wechat_references(items: list[dict], limit: int = 15) -> int:
    """下载 top N 文章全文到 references/（去重，自动更新 index.json）"""
    today = datetime.now().strftime("%Y-%m-%d")
    ref_dir = BASE_DIR / "references" / today
    ref_dir.mkdir(parents=True, exist_ok=True)

    # 从 index.json 读取已有 link，避免重复下载
    existing_refs, existing_links = _load_index_json()

    downloaded = 0
    new_refs = []
    for item in items[:limit]:
        link = item.get("link", "")
        title = item.get("title", "").strip()
        if not link or not title:
            continue

        # 去重：link 已存在则跳过
        if link in existing_links:
            print(f"  ⏭ 已存在（link重复）: {title[:30]}", file=sys.stderr)
            continue

        # 去重：文件名已存在则跳过
        safe_name = re.sub(r'[\\/:*?"<>|]', '', title)[:40]
        save_path = ref_dir / f"{safe_name}.md"
        if save_path.exists():
            print(f"  ⏭ 已存在: {safe_name}.md", file=sys.stderr)
            existing_links.add(link)
            continue

        print(f"  📥 下载: {title[:30]}...", file=sys.stderr)
        snippet = item.get("contentSnippet", "")
        content = download_full_article(link, snippet=snippet)
        if content:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(content)
            downloaded += 1
            existing_links.add(link)
            new_refs.append({
                "title": title,
                "date": today,
                "source": item.get("sourceName", ""),
                "path": f"references/{today}/{safe_name}.md",
                "link": link,
                "style_note": "",
            })
            print(f"     ✅ {safe_name}.md ({len(content)}B)", file=sys.stderr)
        else:
            print(f"     ⚠️ 下载失败", file=sys.stderr)

    # 追加新条目到 index.json
    if new_refs:
        _append_index_json(new_refs)
        print(f"[INFO] index.json 追加 {len(new_refs)} 条新记录", file=sys.stderr)

    print(f"[INFO] 本轮下载 {downloaded} 篇新参考文章", file=sys.stderr)
    return downloaded


# ─── 3. 微博热搜采集 ─────────────────────────────────

def fetch_weibo_trendings() -> list[dict]:
    """通过 mcporter 获取微博热搜"""
    home = os.path.expanduser("~")
    mcporter = os.path.join(home, "npm-global/bin/mcporter")
    env = os.environ.copy()
    env["PATH"] = f"{home}/npm-global/bin:{env.get('PATH', '')}"

    try:
        result = subprocess.run(
            [mcporter, "call", "weibo.get_trendings(limit: 25)"],
            capture_output=True, text=True, timeout=30, env=env,
            cwd=home,
        )
        if result.returncode != 0:
            print(f"[WARN] mcporter 返回码: {result.returncode}", file=sys.stderr)
            print(f"[WARN] stderr: {result.stderr[:500]}", file=sys.stderr)
            return []

        data = json.loads(result.stdout)
        items = []
        for entry in data.get("result", []):
            trending = entry.get("trending", 0)
            if isinstance(trending, (int, float)) and trending > 0:
                items.append({
                    "topic": entry["description"],
                    "hotness": trending,
                    "source": "weibo",
                })
        return items
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        print(f"[WARN] 微博热搜采集失败: {e}", file=sys.stderr)
        return []


# ─── 素材分类 ──────────────────────────────────────────

# 生活向关键词
LIFE_KEYWORDS = [
    # 日常生活
    "天气", "温度", "升温", "降温", "下雨", "出门", "上班", "下班",
    "工资", "放假", "假期", "春节", "中秋", "国庆",
    # 饮食
    "杨梅", "西瓜", "荔枝", "水果", "吃饭", "早餐", "晚餐", "美食",
    "餐厅", "食堂", "厨房", "餐具", "不锈钢",
    # 家庭/情感
    "小孩", "妈妈", "爸爸", "孩子", "父母", "结婚", "恋爱", "爱情",
    "相亲", "分手", "离婚", "家庭", "亲子",
    # 校园
    "高考", "考试", "作文", "学生", "学校", "暑假", "寒暑假", "开学",
    # 社会观察
    "奔跑吧", "综艺", "节目", "道歉", "致歉",
    "黄仁勋", "初恋", "恩爱", "秀",
    # 健康/生活妙招
    "健康", "养生", "睡眠", "熬夜", "运动",
    # 职场
    "面试", "工作", "辞职", "跳槽", "社保", "公积金",
    # 消费
    "省钱", "优惠", "补贴", "涨价", "降价",
    # 城市话题
    "通勤", "地铁", "公交",
]

# 非生活向排除模式（帮助过滤）
NON_LIFE_PATTERNS = [
    # 政治
    "习近平", "总书记", "军委主席", "国事访问", "中朝", "中俄", "中美",
    "外交", "声明", "署名文章", "元首", "贺电", "贺信", "大使", "会谈",
    "朝鲜", "邀请", "会见", "政治局",

    # 国际政治
    "特朗普", "普京", "拜登", "外交部", "国防",
    "韩国", "日本", "朝鲜", "美国", "俄罗斯", "乌克兰",
    "以色列", "伊朗", "巴勒斯坦", "北约",

    # 金融
    "涨停", "跌停", "股市", "券商", "基金", "期货", "A股", "港股",
    "爆仓", "大涨", "杀跌", "多头", "空头",

    # 腐败/司法
    "双开", "开除", "落马", "被捕", "拘留", "判刑", "被查",

    # 营销
    "MCN", "团购", "直播间", "带货",
]


def classify_life(item: dict) -> bool:
    """判断是否为生活向话题"""
    title = item.get("topic", "") or item.get("title", "")
    if not title:
        return False

    # 如有非生活模式，跳过
    if any(kw in title for kw in NON_LIFE_PATTERNS):
        return False

    # 如有生活关键词
    if any(kw in title for kw in LIFE_KEYWORDS):
        return True

    return False


def merge_materials(
    weibo_items: list[dict],
    wechat_items: list[dict],
) -> dict:
    """合并素材，按类别分组"""
    materials = {
        "weibo_life": [],
        "weibo_other": [],
        "wechat_life": [],
        "wechat_other": [],
    }

    for item in weibo_items:
        if classify_life(item):
            materials["weibo_life"].append(item)
        else:
            materials["weibo_other"].append(item)

    for item in wechat_items:
        if classify_life(item):
            materials["wechat_life"].append(item)
        else:
            materials["wechat_other"].append(item)

    return materials


# ─── 输出 ──────────────────────────────────────────────

def _push_weixin(message: str) -> bool:
    """推送消息到微信渠道（通过 iLink API）"""
    import random as _rand

    base_url = os.environ.get("WEIXIN_BASE_URL", "https://ilinkai.weixin.qq.com")
    token = os.environ.get("WEIXIN_TOKEN", "")
    account_id = os.environ.get("WEIXIN_ACCOUNT_ID", "")
    home_channel = os.environ.get("WEIXIN_HOME_CHANNEL", "")

    if not all([token, account_id, home_channel]):
        print("[WARN] 微信推送跳过：缺少环境变量", file=sys.stderr)
        return False

    # 读取 context_token
    ct_path = Path("/opt/data/weixin/accounts") / f"{account_id}.context-tokens.json"
    ctx_token = ""
    if ct_path.exists():
        try:
            ctokens = json.loads(ct_path.read_text(encoding="utf-8"))
            ctx_token = ctokens.get(home_channel, "")
        except Exception:
            pass

    msg = {
        "from_user_id": "",
        "to_user_id": home_channel,
        "client_id": account_id,
        "message_type": 2,
        "message_state": 2,
        "context_token": ctx_token,
        "item_list": [{"type": 1, "text_item": {"text": message}}],
    }
    payload = {"msg": msg, "base_info": {"channel_version": "2.2.0"}}
    body = json.dumps(payload, separators=(",", ":")).encode()

    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Content-Length": str(len(body)),
        "X-WECHAT-UIN": str(_rand.randint(100_000_000, 999_999_999)),
        "iLink-App-Id": "bot",
        "iLink-App-ClientVersion": str((2 << 16) | (2 << 8) | 0),
        "Authorization": f"Bearer {token}",
    }

    try:
        req = Request(
            f"{base_url}/ilink/bot/sendmessage",
            data=body, headers=headers, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("errcode") == 0 or not result:
                print("[INFO] ✅ 微信推送成功", file=sys.stderr)
                return True
            else:
                print(f"[WARN] 微信推送失败: {result}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"[WARN] 微信推送异常: {e}", file=sys.stderr)
        return False


def format_for_agent(materials: dict) -> str:
    """格式化为 agent 可用的素材文本"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"📊 素材采集报告 ⏰ {now}", ""]

    # ── 微信热榜（生活向） ──
    lines.append("═══ 📱 微信24h热榜 · 生活向（风格参考）═══")
    wechat_life = materials.get("wechat_life", [])
    if wechat_life:
        for i, item in enumerate(wechat_life[:15], 1):
            title = item.get("title", "")
            day = item.get("_day", "")
            source = item.get("sourceName", "")
            lines.append(f"{i}. {title}")
            lines.append(f"   📅 {day}  {source}")
    else:
        lines.append("  (无生活向内容)")

    lines.append("")

    # ── 微博热搜（全部，排序，生活向标记） ──
    lines.append("═══ 🔥 微博热搜（生活向话题标记为 🧩）═══")
    weibo_all = materials.get("weibo_life", []) + materials.get("weibo_other", [])
    weibo_all.sort(key=lambda x: x.get("hotness", 0), reverse=True)
    if weibo_all:
        for i, item in enumerate(weibo_all[:20], 1):
            hot = item.get("hotness", 0)
            tag = "🧩" if classify_life(item) else "📌"
            lines.append(f"{tag} #{i} {item['topic']}  (热度: {hot:,})")
    else:
        lines.append("  (无数据)")

    lines.append("")

    # ── 微信热榜（非生活向，仅标题） ──
    wechat_other = materials.get("wechat_other", [])
    if wechat_other:
        lines.append("═══ 📱 微信热榜 · 其他话题（供参考）═══")
        for i, item in enumerate(wechat_other[:10], 1):
            lines.append(f"  {i}. {item.get('title', '')}")

    lines.append("")
    lines.append("─── 写作主题建议 ───")
    lines.append("以上素材已按【微信热榜 → 微博热搜】顺序排列。")
    lines.append("微信热榜是风格参考源，不是内容素材。")
    lines.append("建议从 🧩 标记的微博热搜中选择一个生活向话题写深写透。")
    lines.append("写前先抓取1-2篇微信热榜原文分析写作风格。")

    return "\n".join(lines)


# ─── 主流程 ─────────────────────────────────────────────

def main() -> int:
    print("[INFO] 开始采集素材...", file=sys.stderr)

    # 只跑微信采集模式
    if "--fetch-only" in sys.argv:
        ok = ensure_wechat_data()
        return 0 if ok else 1

    # ── 第1步：微信热榜 ──
    ensure_wechat_data()
    print("[INFO] 📱 读取微信热榜...", file=sys.stderr)
    wechat_items = load_wechat_hotlist(days=2)
    print(f"[INFO] 微信热榜: {len(wechat_items)} 条", file=sys.stderr)

    # ── 第2步：全文下载（写前风格参考，top 15，去重） ──
    wechat_life_items = [item for item in wechat_items if classify_life(item)]
    print(f"[INFO] 📥 下载文章全文（top 15）...", file=sys.stderr)
    dl_count = download_wechat_references(wechat_life_items, limit=15)

    # ── 第3步：微博热搜 ──
    if "--no-weibo" in sys.argv:
        weibo_items = []
    else:
        print("[INFO] 🐾 抓取微博热搜...", file=sys.stderr)
        weibo_items = fetch_weibo_trendings()
        print(f"[INFO] 微博热搜: {len(weibo_items)} 条", file=sys.stderr)

    # 合并分类
    materials = merge_materials(weibo_items, wechat_items)

    # 输出给 agent
    output = format_for_agent(materials)
    print(output)

    # ── 第4步：推送到微信 ──
    print("[INFO] 📲 推送选题到微信...", file=sys.stderr)
    _push_weixin(output)

    print("=== COLLECT_DONE ===", file=sys.stderr)
    wb_life = len(materials["weibo_life"])
    wc_life = len(materials["wechat_life"])
    print(f"[INFO] 素材就绪: 微信热榜={len(wechat_items)}条(生活向={wc_life}), "
          f"微博={len(weibo_items)}条(生活向={wb_life}), "
          f"总计生活素材={wb_life + wc_life}条", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
