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
from city_utils import slugify, city_filename
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import requests

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

API_URL = "https://api.deepseek.com/chat/completions"
API_MODEL = "deepseek-chat"
WIKI_API = "https://en.wikipedia.org/w/api.php"

BASE_DIR = Path(__file__).resolve().parent
CITIES_DIR = BASE_DIR / "cities"
SITEMAP_PATH = BASE_DIR / "sitemap.xml"
CITIES_JSON = BASE_DIR / "cities.json"
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://yz20260416.github.io").rstrip("/")


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


# ---------------------------------------------------------------------------
# 维基百科材料抓取
# ---------------------------------------------------------------------------

def fetch_wiki_culture(city: str, country: str = "") -> str:
    """抓维基百科该城市条目的 History/Culture 章节原文。失败返回空字符串。"""
    headers = {"User-Agent": "TravelGuidesBot/1.0 (educational project)"}

    def _query(title: str) -> str:
        params = {
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "format": "json",
            "redirects": 1,
            "titles": title,
        }
        try:
            resp = requests.get(WIKI_API, params=params, headers=headers, timeout=30)
            if resp.status_code != 200:
                return ""
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                extract = page.get("extract", "")
                if extract and len(extract) > 200:
                    # 只取前 3000 字符，避免 prompt 过长
                    return extract[:3000]
            return ""
        except Exception as e:
            print(f"  [warn] wiki 查询 '{title}' 失败: {e}", file=sys.stderr)
            return ""

    # 依次尝试：城市名+国家、城市名、城市名 (国家)
    for title in [f"{city}", f"{city}, {country}", f"{city} ({country})"]:
        text = _query(title)
        if text:
            print(f"  [wiki] {city}: 拿到 {len(text)} 字符材料")
            return text

    print(f"  [wiki] {city}: 未找到材料，跳过人文段", file=sys.stderr)
    return ""


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def related_for(city_data):
    if "related" in city_data:
        return city_data["related"]
    region = city_data.get("region", "")
    same_region = [c["name"] for c in CITIES_DATA if c.get("region") == region and c["name"] != city_data["name"]]
    return same_region[:3]


# ---------------------------------------------------------------------------
# DeepSeek API
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """You are a travel writer. Produce factual, concise travel guide content for the city: {city}.

{culture_section}

Return ONLY a JSON object (no markdown, no code fences) with exactly this schema:

{{
  "intro": "2-3 sentences overview of the city and why/when to visit.",
  "culture": "{culture_instruction}",
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
- In the "culture" field, avoid references to modern political systems or ideologies; focus on culture, history, customs, geography, and daily life.
- Output valid JSON only.
"""

CULTURE_INSTRUCTION_WITH_MATERIAL = (
    "200-300 words on the local character of this city. "
    "Using ONLY the provided Wikipedia material, extract 1-2 SPECIFIC details that a generic travel guide would miss "
    "(a named tradition, a local custom, a historical quirk, a neighborhood's character). "
    "For each detail, explain in one sentence why a visitor should care. "
    "Do NOT write generic phrases like 'rich history' or 'vibrant culture'. "
    "Do NOT summarize the entire Wikipedia article — pick specific details."
)

CULTURE_INSTRUCTION_FALLBACK = (
    "200-300 words on the local character of this city. "
    "Be specific: name one local tradition, custom, or historical detail that a generic guide would miss, "
    "and explain why a visitor should care. Avoid generic phrases."
)


def call_deepseek(city: str, api_key: str, culture_material: str = "", retries: int = 3) -> dict:
    if culture_material:
        culture_section = (
            "Below is reference material from Wikipedia about this city. "
            "Use it to extract SPECIFIC local details, not generic descriptions.\n\n"
            f"--- WIKIPEDIA MATERIAL ---\n{culture_material}\n--- END MATERIAL ---"
        )
        culture_instruction = CULTURE_INSTRUCTION_WITH_MATERIAL
    else:
        culture_section = ""
        culture_instruction = CULTURE_INSTRUCTION_FALLBACK

    prompt = PROMPT_TEMPLATE.format(
        city=city,
        culture_section=culture_section,
        culture_instruction=culture_instruction,
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": API_MODEL,
        "messages": [
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": prompt},
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


POLITICAL_TERMS = [
    "communist", "capitalist", "socialist", "imperialist",
    "regime", "dictatorship", "authoritarian",
]

def sanitize_culture(text: str) -> str:
    """替换文化段里可能引发不必要联想的政治分期表述。"""
    if not text:
        return text
    out = text
    out = out.replace(
        "through imperial, republican, and communist eras",
        "across more than two millennia of continuous history"
    )
    out = out.replace(
        "imperial, republican, and communist eras",
        "more than two millennia of continuous history"
    )
    out = out.replace(
        "imperial, republican, and communist",
        "more than two millennia of"
    )
    # 兜底：逐词替换，保留句子通顺
    for term in POLITICAL_TERMS:
        out = out.replace(term, "")
    # 清理替换后可能出现的多余空格和标点
    import re as _re
    out = _re.sub(r"\s{2,}", " ", out)
    out = _re.sub(r"\s+([,.;:])", r"\1", out)
    return out.strip()


def render_html(city_data: dict, data: dict, has_culture_material: bool = False) -> str:
    city = city_data["name"]
    intro = esc(data.get("intro", ""))
    culture = esc(sanitize_culture(data.get("culture", "")))
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

    culture_section = ""
    if culture:
        culture_section = f"""
      <h2>Local Character</h2>
      <p>{culture}</p>
"""

    source_note = ""
    if has_culture_material:
        source_note = (
            f'\n      <p class="source-note">Local character section based on public Wikipedia material; '
            f'generated by AI on {date.today().isoformat()}.</p>'
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
{culture_section}
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
{source_note}
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
    try:
        from build_index import main as build_index_main
        build_index_main()
    except Exception as e:
        print(f"[warn] 更新 cities-index.json 失败: {e}", file=sys.stderr)


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
        country = city_data.get("country", "")
        print(f"[{i}/{len(todo)}] 生成 {city} ...")
        try:
            culture_material = fetch_wiki_culture(city, country)
            data = call_deepseek(city, api_key, culture_material=culture_material)
            html = render_html(city_data, data, has_culture_material=bool(culture_material))
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