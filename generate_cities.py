#!/usr/bin/env python3
"""
generate_cities.py

读取 cities.json 配置，调用 DeepSeek API 生成城市旅行指南页面。

用法:
    python generate_cities.py                 # 生成所有缺失的城市
    python generate_cities.py --force         # 覆盖已存在的文件
    python generate_cities.py --only Tokyo    # 只生成指定城市
    python generate_cities.py --dry-run       # 只打印计划，不调用 API
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import requests

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

API_URL = "https://api.deepseek.com/chat/completions"
API_MODEL = "deepseek-chat"

BASE_DIR = Path(__file__).resolve().parent
CITIES_DIR = BASE_DIR / "cities"
SITEMAP_PATH = BASE_DIR / "sitemap.xml"
CITIES_JSON = BASE_DIR / "cities.json"
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://yz20260416.github.io").rstrip("/")

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

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def city_filename(name: str) -> str:
    return f"{slugify(name)}.html"


def related_for(city_data):
    if "related" in city_data:
        return city_data["related"]
    # 默认取同 region 的前 3 个城市
    region = city_data.get("region", "")
    same_region = [c["name"] for c in CITIES_DATA if c.get("region") == region and c["name"] != city_data["name"]]
    return same_region[:3]


# ---------------------------------------------------------------------------
# DeepSeek API
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """You are a travel writer. Produce factual, concise travel guide content for the city: {city}.

Return ONLY a JSON object (no markdown, no code fences) with exactly this schema:

{{
  "intro": "2-3 sentences overview of the city and why/when to visit.",
  "months": [
    {{"month": "January", "temperature": "2-10°C", "rainfall": "Low", "crowds": "Low", "recommendation": "Good"}},
    ... exactly 12 entries, January through December ...
  ],
  "attractions": [
    {{"name": "Attraction name", "description": "One sentence description."}},
    ... exactly 5 entries ...
  ],
  "practical": {{
    "currency": "e.g. Japanese Yen (JPY, ¥)",
    "language": "e.g. Japanese (English signage is common in tourist areas)",
    "timezone": "e.g. JST (UTC+9)",
    "visa": "One sentence about visa requirements for typical international visitors."
  }},
  "faq": [
    {{"question": "Question?", "answer": "Answer."}},
    ... exactly 3 entries ...
  ]
}}

Rules:
- rainfall and crowds must be one of: Low, Moderate, High (for rainfall) / Low, Medium, High (for crowds).
- recommendation must be one of: Excellent, Very Good, Good, Fair.
- Use realistic seasonal data for {city}.
- Keep descriptions to a single sentence.
- Output valid JSON only.
"""


def call_deepseek(city: str, api_key: str, retries: int = 3) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": API_MODEL,
        "messages": [
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": PROMPT_TEMPLATE.format(city=city)},
        ],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as exc:
            last_err = exc
            print(f"  [warn] {city} 第 {attempt} 次调用失败: {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"{city} 生成失败: {last_err}")


# ---------------------------------------------------------------------------
# HTML 渲染
# ---------------------------------------------------------------------------

def esc(text) -> str:
    return escape(str(text))


def render_html(city_data: dict, data: dict) -> str:
    city = city_data["name"]
    intro = esc(data.get("intro", ""))
    months = data.get("months", [])
    attractions = data.get("attractions", [])
    practical = data.get("practical", {})
    faq = data.get("faq", [])

    month_rows = "\n".join(
        f"""            <tr>
              <td>{esc(m.get('month', ''))}</td>
              <td>{esc(m.get('temperature', ''))}</td>
              <td>{esc(m.get('rainfall', ''))}</td>
              <td>{esc(m.get('crowds', ''))}</td>
              <td>{esc(m.get('recommendation', ''))}</td>
            </tr>"""
        for m in months
    )

    attraction_items = "\n".join(
        f"        <li><strong>{esc(a.get('name', ''))}</strong> — {esc(a.get('description', ''))}</li>"
        for a in attractions
    )

    practical_items = "\n".join(
        [
            f"        <li><strong>Currency:</strong> {esc(practical.get('currency', ''))}</li>",
            f"        <li><strong>Language:</strong> {esc(practical.get('language', ''))}</li>",
            f"        <li><strong>Time Zone:</strong> {esc(practical.get('timezone', ''))}</li>",
            f"        <li><strong>Visa:</strong> {esc(practical.get('visa', ''))}</li>",
        ]
    )

    faq_items = "\n\n".join(
        f"""        <dt>{esc(q.get('question', ''))}</dt>
        <dd>{esc(q.get('answer', ''))}</dd>"""
        for q in faq
    )

    related = related_for(city_data)
    related_items = "\n".join(
        f'          <li><a href="{city_filename(r)}">{esc(r)}</a></li>'
        for r in related
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Best Time to Visit {esc(city)} - Travel Guides</title>
  <meta name="description" content="Monthly weather, crowds, and travel tips to help you find the best time to visit {esc(city)}.">
  <link rel="stylesheet" href="../css/style.css">
</head>
<body>
  <div class="container">
    <header>
      <h1>Best Time to Visit {esc(city)}</h1>
      <p>{intro}</p>
    </header>

    <main>
      <h2>Monthly Overview</h2>
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Month</th>
              <th>Temperature</th>
              <th>Rainfall</th>
              <th>Crowds</th>
              <th>Recommendation</th>
            </tr>
          </thead>
          <tbody>
{month_rows}
          </tbody>
        </table>
      </div>

      <h2>Top 5 Attractions</h2>
      <ol>
{attraction_items}
      </ol>

      <h2>Practical Information</h2>
      <ul>
{practical_items}
      </ul>

      <h2>FAQ</h2>
      <dl class="faq">
{faq_items}
      </dl>

      <nav class="related-cities">
        <h2>Related Cities</h2>
        <ul>
{related_items}
        </ul>
      </nav>
    </main>

    <footer>
      <p>&copy; 2026 Travel Guides</p>
    </footer>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# sitemap
# ---------------------------------------------------------------------------

def rebuild_sitemap() -> None:
    today = date.today().isoformat()
    urls = [
        (f"{SITE_BASE_URL}/index.html", "weekly", "1.0"),
    ]
    for html_file in sorted(CITIES_DIR.glob("*.html")):
        urls.append((f"{SITE_BASE_URL}/cities/{html_file.name}", "monthly", "0.8"))

    entries = "\n".join(
        f"""  <url>
    <loc>{escape(loc)}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>{freq}</changefreq>
    <priority>{prio}</priority>
  </url>"""
        for loc, freq, prio in urls
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{entries}
</urlset>
"""
    SITEMAP_PATH.write_text(xml, encoding="utf-8")
    print(f"[sitemap] 已更新 {SITEMAP_PATH}（{len(urls)} 条 URL）")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="生成城市旅行指南页面。")
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

    todo = []
    for city_data in targets:
        out = CITIES_DIR / city_filename(city_data["name"])
        if out.exists() and not args.force:
            print(f"[skip] {city_data['name']} 已存在: {out.name}")
            continue
        todo.append(city_data)

    if not todo:
        print("[info] 没有需要生成的城市。")
        rebuild_sitemap()
        return 0

    print(f"[info] 计划生成 {len(todo)} 个城市: {', '.join(c['name'] for c in todo)}")
    if args.dry_run:
        return 0

    for i, city_data in enumerate(todo, 1):
        city = city_data["name"]
        print(f"[{i}/{len(todo)}] 生成 {city} ...")
        try:
            data = call_deepseek(city, api_key)
            html = render_html(city_data, data)
            out = CITIES_DIR / city_filename(city)
            out.write_text(html, encoding="utf-8")
            print(f"  -> 已写入 {out}")
        except Exception as exc:
            print(f"  [error] {city} 失败: {exc}", file=sys.stderr)
        time.sleep(1)

    rebuild_sitemap()
    return 0


if __name__ == "__main__":
    sys.exit(main())