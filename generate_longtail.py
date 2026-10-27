#!/usr/bin/env python3
"""
generate_longtail.py

读取 cities.json 配置，为每个城市生成 4 个长尾页面：
- weather, attractions, itinerary, budget

用法:
    python generate_longtail.py                 # 生成所有缺失的长尾页面
    python generate_longtail.py --force         # 覆盖已存在的文件
    python generate_longtail.py --only Tokyo    # 只生成指定城市
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

API_URL = "https://api.deepseek.com/chat/completions"
API_MODEL = "deepseek-chat"

BASE_DIR = Path(__file__).resolve().parent
CITIES_DIR = BASE_DIR / "cities"
CITIES_JSON = BASE_DIR / "cities.json"

# 从 aider.sh 读取 API Key
def get_api_key():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    aider_sh = BASE_DIR / "aider.sh"
    if aider_sh.exists():
        try:
            content = aider_sh.read_text()
            match = re.search(r'OPENAI_API_KEY="([^"]+)"', content)
            if match:
                return match.group(1)
        except Exception as e:
            print(f"[warn] 读取 aider.sh 失败: {e}", file=sys.stderr)
    return None

API_KEY = get_api_key()

# 加载城市配置
def load_cities():
    if not CITIES_JSON.exists():
        print(f"[error] 找不到 {CITIES_JSON}", file=sys.stderr)
        sys.exit(1)
    with open(CITIES_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)

CITIES_DATA = load_cities()

# 长尾页面类型
LONGTAIL_TYPES = [
    {
        "suffix": "weather",
        "title": "Weather by Month",
        "prompt": "detailed monthly weather guide with temperature, rainfall, humidity, and best months to visit. Include a table with 12 rows (Jan-Dec)."
    },
    {
        "suffix": "attractions",
        "title": "Top 10 Attractions",
        "prompt": "top 10 must-see attractions with descriptions, ticket prices, opening hours, and visiting tips. Format as a numbered list."
    },
    {
        "suffix": "itinerary",
        "title": "3-Day Itinerary",
        "prompt": "perfect 3-day itinerary with morning/afternoon/evening schedules, restaurant recommendations, and practical tips. Format as day-by-day sections."
    },
    {
        "suffix": "budget",
        "title": "Travel Cost Guide",
        "prompt": "complete budget breakdown for backpacker, mid-range, and luxury travelers. Include accommodation, food, transport, and activity costs. Format as a table."
    }
]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def city_filename(name: str) -> str:
    return f"{slugify(name)}.html"


def longtail_filename(name: str, suffix: str) -> str:
    return f"{slugify(name)}-{suffix}.html"


# ---------------------------------------------------------------------------
# DeepSeek API
# ---------------------------------------------------------------------------

def call_deepseek(city: str, longtail_type: dict, api_key: str, retries: int = 3) -> str:
    prompt = f"""Write a comprehensive travel guide section for {city}: {longtail_type['prompt']}.

Format as clean HTML with:
- An <h2> title
- Introduction paragraph
- Main content (tables, lists, or structured sections as specified)
- Practical tips section
- Keep it factual and helpful for travelers

Output only the HTML content, no markdown code fences."""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": API_MODEL,
        "messages": [
            {"role": "system", "content": "You write factual travel guide content. Output clean HTML only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            # 移除可能的 markdown 代码块标记
            content = re.sub(r'^```html\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            return content.strip()
        except Exception as exc:
            last_err = exc
            print(f"  [warn] {city} {longtail_type['suffix']} 第 {attempt} 次失败: {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"{city} {longtail_type['suffix']} 生成失败: {last_err}")


# ---------------------------------------------------------------------------
# HTML 渲染
# ---------------------------------------------------------------------------

def render_longtail_html(city_data: dict, longtail_type: dict, content: str) -> str:
    city = city_data["name"]
    title = f"{city} {longtail_type['title']}"
    
    # 生成相关链接
    slug = slugify(city)
    related_links = f"""
            <section class="related-links">
                <h3>More {city} Guides</h3>
                <ul>
                    <li><a href="{slug}.html">Best Time to Visit {city}</a></li>
                    <li><a href="{slug}-weather.html">{city} Weather</a></li>
                    <li><a href="{slug}-attractions.html">{city} Attractions</a></li>
                    <li><a href="{slug}-itinerary.html">{city} Itinerary</a></li>
                    <li><a href="{slug}-budget.html">{city} Budget</a></li>
                </ul>
            </section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{title} - Complete travel guide with practical information for visitors.">
    <title>{title} | Travel Guides</title>
    <link rel="stylesheet" href="../css/style.css">
</head>
<body>
    <header>
        <nav>
            <a href="../index.html">Home</a> > <a href="{slug}.html">{city}</a> > {longtail_type['title']}
        </nav>
    </header>
    
    <main>
        <article>
            {content}
            
            {related_links}
        </article>
    </main>
    
    <footer>
        <p>&copy; 2026 Travel Guides</p>
    </footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="生成城市长尾页面。")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 HTML 文件")
    parser.add_argument("--only", action="append", default=[], metavar="CITY",
                        help="只生成指定城市（可多次使用）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不调用 API")
    args = parser.parse_args()

    CITIES_DIR.mkdir(parents=True, exist_ok=True)

    targets = CITIES_DATA
    if args.only:
        wanted = {c.lower() for c in args.only}
        targets = [c for c in CITIES_DATA if c["name"].lower() in wanted]
        missing = wanted - {c["name"].lower() for c in targets}
        if missing:
            print(f"[error] 未知城市: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1

    api_key = API_KEY
    if not api_key and not args.dry_run:
        print(f"[error] 无法获取 API Key", file=sys.stderr)
        return 1

    # 检查需要生成的任务
    todo = []
    for city_data in targets:
        for lt in LONGTAIL_TYPES:
            out = CITIES_DIR / longtail_filename(city_data["name"], lt["suffix"])
            if out.exists() and not args.force:
                continue
            todo.append((city_data, lt))

    if not todo:
        print("[info] 没有需要生成的长尾页面。")
        return 0

    print(f"[info] 计划生成 {len(todo)} 个长尾页面")
    if args.dry_run:
        for city_data, lt in todo[:10]:  # 只显示前10个
            print(f"  - {city_data['name']}: {lt['suffix']}")
        if len(todo) > 10:
            print(f"  ... 还有 {len(todo)-10} 个")
        return 0

    for i, (city_data, lt) in enumerate(todo, 1):
        city = city_data["name"]
        print(f"[{i}/{len(todo)}] 生成 {city} - {lt['suffix']} ...")
        try:
            content = call_deepseek(city, lt, api_key)
            html = render_longtail_html(city_data, lt, content)
            out = CITIES_DIR / longtail_filename(city, lt["suffix"])
            out.write_text(html, encoding="utf-8")
            print(f"  -> 已写入 {out}")
        except Exception as exc:
            print(f"  [error] {city} {lt['suffix']} 失败: {exc}", file=sys.stderr)
        time.sleep(1)

    print(f"\n[info] 完成！共生成 {len(todo)} 个长尾页面。")
    return 0


if __name__ == "__main__":
    sys.exit(main())