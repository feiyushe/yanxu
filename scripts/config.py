"""yanxu (燕叙) - 配置常量
微信公众号优质内容采集
"""

from pathlib import Path

# ─── 路径 ────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"

# ─── RSS 源 ──────────────────────────────────────────────

RSS_URLS: dict[str, str] = {
    "wechat_hot": "https://rsshub.rssforever.com/tophub/WnBe01o371",
    "wxbyg":      "https://rsshub.rssforever.com/telegram/channel/wxbyg",
    "huxiu":      "https://rss.huxiu.com/",
    "36kr":       "https://rsshub.rssforever.com/36kr/hot-list",
}

SOURCE_MAP: dict[str, str] = {
    "wechat_hot": "📱 微信24h热文榜",
    "wxbyg":      "📢 微信搬运",
    "huxiu":      "🦊 虎嗅",
    "36kr":       "📡 36氪",
}

# ─── 内容筛选 ────────────────────────────────────────────

# 质量关键词（标题包含以下词视为高质量）
QUALITY_KEYWORDS: list[str] = [
    "深度", "解读", "分析", "原创", "独家",
    "指南", "教程", "干货", "实践", "经验",
    "报告", "数据", "趋势", "洞察", "观察",
]

# 排除关键词（标题包含以下词直接跳过）
EXCLUDE_TITLE: list[str] = [
    "广告", "推广", "赞助",
]

# ─── 存储配置 ────────────────────────────────────────────

MAX_DAILY_ITEMS: int = 200
REMOVE_READ_COUNT_TAG: bool = True