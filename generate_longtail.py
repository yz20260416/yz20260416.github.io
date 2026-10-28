#!/usr/bin/env python3
"""
generate_longtail.py

读取 cities.json 配置，为每个城市生成 4 个长尾页面：
- weather, attractions, itinerary, budget

weather 类型会调用 Open-Meteo 拿真实历史天气数据作为 prompt 输入；
其他类型走原来的纯 AI 生成路径。

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
from city_utils import slugify, city_filename
from pathlib import Path
from statistics import mean
from datetime import date

import requests

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

API_URL = "https://api.deepseek.com/chat/completions"
API_MODEL = "deepseek-chat"

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

HIST_START = "2021-01-01"
HIST_END = "2025-12-31"

BASE_DIR = Path(__file__).resolve().parent
CITIES_DIR = BASE_DIR / "cities"
CITIES_JSON = BASE_DIR / "cities.json"


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


def load_cities():
    if not CITIES_JSON.exists():
        print(f"[error] 找不到 {CITIES_JSON}", file=sys.stderr)
        sys.exit(1)
    with open(CITIES_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)


CITIES_DATA = load_cities()

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
# Open-Meteo 真实天气数据
# ---------------------------------------------------------------------------

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def fetch_weather_data(city: str, country: str = "") -> dict:
    """调 Open-Meteo 拿过去 5 年真实天气，算出 12 个月的统计。失败返回 {}。"""
    headers = {"User-Agent": "TravelGuidesBot/1.0 (educational project)"}

    ALIASES = {
        "Marrakech": "Marrakesh",
        "St. Petersburg": "Saint Petersburg",
    }
    query_city = ALIASES.get(city, city)

    # 1. geocoding
    lat = lon = None
    for query in [query_city, f"{query_city}, {country}" if country else query_city]:
        try:
            resp = requests.get(
                GEOCODE_URL,
                params={"name": query, "count": 1, "language": "en", "format": "json"},
                headers=headers, timeout=30,
            )
            if resp.status_code != 200:
                continue
            results = resp.json().get("results", [])
            if results:
                lat = results[0]["latitude"]
                lon = results[0]["longitude"]
                break
        except Exception as e:
            print(f"  [warn] geocode '{query}' 失败: {e}", file=sys.stderr)
            continue

    if lat is None:
        print(f"  [weather] {city}: geocoding 未找到坐标，降级为纯 AI", file=sys.stderr)
        return {}

    # 2. 拉历史每日数据
    try:
        resp = requests.get(
            ARCHIVE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": HIST_START,
                "end_date": HIST_END,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "timezone": "auto",
            },
            headers=headers, timeout=60,
        )
        if resp.status_code != 200:
            print(f"  [weather] {city}: archive HTTP {resp.status_code}，降级", file=sys.stderr)
            return {}
        daily = resp.json().get("daily", {})
    except Exception as e:
        print(f"  [warn] {city} archive 失败: {e}", file=sys.stderr)
        return {}

    dates = daily.get("time", [])
    tmax = daily.get("temperature_2m_max", [])
    tmin = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])

    if not dates:
        return {}

    # 3. 按月份分组统计
    buckets = {m: {"tmax": [], "tmin": [], "precip_days": 0, "total_days": 0}
               for m in range(1, 13)}

    for i, d in enumerate(dates):
        try:
            month = int(d[5:7])
        except Exception:
            continue
        b = buckets[month]
        b["total_days"] += 1
        if i < len(tmax) and tmax[i] is not None:
            b["tmax"].append(tmax[i])
        if i < len(tmin) and tmin[i] is not None:
            b["tmin"].append(tmin[i])
        if i < len(precip) and precip[i] is not None and precip[i] > 1.0:
            b["precip_days"] += 1

    monthly = []
    for m in range(1, 13):
        b = buckets[m]
        if not b["tmax"]:
            monthly.append({"month": MONTH_NAMES[m-1], "avg_high": None,
                            "avg_low": None, "rain_days": None})
            continue
        monthly.append({
            "month": MONTH_NAMES[m-1],
            "avg_high": round(mean(b["tmax"]), 1),
            "avg_low": round(mean(b["tmin"]), 1) if b["tmin"] else None,
            "rain_days": round(b["precip_days"] / 5.0, 1),
        })

    print(f"  [weather] {city}: 拿到 2021-2025 真实数据（{len(dates)} 天）")
    return {"monthly": monthly, "source": "Open-Meteo", "years": "2021-2025"}


def format_weather_context(wd: dict) -> str:
    """把真实天气统计格式化成 prompt 输入。"""
    lines = ["Real historical weather data (2021-2025 averages):"]
    for m in wd["monthly"]:
        if m["avg_high"] is None:
            lines.append(f"- {m['month']}: data unavailable")
        else:
            low = f"{m['avg_low']}°C" if m["avg_low"] is not None else "n/a"
            lines.append(
                f"- {m['month']}: avg high {m['avg_high']}°C, avg low {low}, "
                f"avg rain days per month {m['rain_days']} (>1mm threshold)"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def longtail_filename(name: str, suffix: str) -> str:
    return f"{slugify(name)}-{suffix}.html"


# ---------------------------------------------------------------------------
# DeepSeek API
# ---------------------------------------------------------------------------

def call_deepseek(city: str, longtail_type: dict, api_key: str,
                  weather_data: dict = None, retries: int = 3) -> str:
    if longtail_type["suffix"] == "weather" and weather_data:
        real = format_weather_context(weather_data)
        prompt = f"""Write a comprehensive travel weather guide for {city}.

USE THIS REAL DATA for the temperature and rainfall columns:
{real}

Requirements:
- The 12-row table MUST use EXACTLY these 7 columns in this order:
  Month | Avg High (°C) | Avg Low (°C) | Avg Rain Days/Month | Rainfall | Crowds | Recommendation
- Use the real avg high / avg low / avg rain days values provided above.
- For "Rainfall" column, translate rain days into Low / Moderate / High based on the actual count
  (0-3 days = Low, 4-8 = Moderate, 9+ = High).
- For "Crowds" column, use general seasonal knowledge (Low / Medium / High).
- For "Recommendation" column, base it on the real temperature + rainfall data.
- Add a short opening paragraph (80-120 words) that interprets the data for travelers:
  name 1-2 specific months where weather is best/worst and say what that means practically.

Format as clean HTML with:
- An <h2> title
- Opening interpretation paragraph
- The 12-row data table
- A "Practical tips" section (3-5 bullets)

Output only the HTML content, no markdown code fences."""
    else:
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
        "max_tokens": 2500,
    }

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
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

def render_longtail_html(city_data: dict, longtail_type: dict, content: str,
                         weather_data: dict = None) -> str:
    city = city_data["name"]
    title = f"{city} {longtail_type['title']}"

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

    source_note = ""
    if longtail_type["suffix"] == "weather" and weather_data:
        source_note = (
            f'\n        <p class="source-note">Weather table based on real historical data from '
            f'Open-Meteo ({weather_data["years"]}). Generated by AI on {date.today().isoformat()}.</p>'
        )

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
            {source_note}
            
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
    parser.add_argument("--type", action="append", default=[], metavar="TYPE",
                        help="只生成指定长尾类型（weather/attractions/itinerary/budget），可多次使用")
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

    allowed_types = set(args.type) if args.type else None
    if allowed_types:
        unknown = allowed_types - {lt["suffix"] for lt in LONGTAIL_TYPES}
        if unknown:
            print(f"[error] 未知类型: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1

    todo = []
    for city_data in targets:
        for lt in LONGTAIL_TYPES:
            if allowed_types and lt["suffix"] not in allowed_types:
                continue
            out = CITIES_DIR / longtail_filename(city_data["name"], lt["suffix"])
            if out.exists() and not args.force:
                continue
            todo.append((city_data, lt))

    if not todo:
        print("[info] 没有需要生成的长尾页面。")
        return 0

    print(f"[info] 计划生成 {len(todo)} 个长尾页面")
    if args.dry_run:
        for city_data, lt in todo[:10]:
            print(f"  - {city_data['name']}: {lt['suffix']}")
        if len(todo) > 10:
            print(f"  ... 还有 {len(todo)-10} 个")
        return 0

    for i, (city_data, lt) in enumerate(todo, 1):
        city = city_data["name"]
        country = city_data.get("country", "")
        print(f"[{i}/{len(todo)}] 生成 {city} - {lt['suffix']} ...")
        try:
            weather_data = None
            if lt["suffix"] == "weather":
                weather_data = fetch_weather_data(city, country)
                time.sleep(2)  # 对 Open-Meteo 温和一些
            content = call_deepseek(city, lt, api_key, weather_data=weather_data)
            html = render_longtail_html(city_data, lt, content, weather_data=weather_data)
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
