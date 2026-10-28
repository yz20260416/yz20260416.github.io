#!/usr/bin/env python3
"""从 cities.json 生成 cities-index.json，供首页 JS 读取。"""

import json
from pathlib import Path
from city_utils import slugify

BASE_DIR = Path(__file__).resolve().parent
CITIES_JSON = BASE_DIR / "cities.json"
INDEX_JSON = BASE_DIR / "cities-index.json"

REGION_EMOJI = {
    "asia": "🏯",
    "europe": "🏛️",
    "americas": "🗽",
    "africa": "🦁",
    "oceania": "🏝️",
    "middle-east": "🕌",
}

def main():
    cities = json.loads(CITIES_JSON.read_text(encoding="utf-8"))
    out = []
    for c in cities:
        out.append({
            "name": c["name"],
            "country": c.get("country", ""),
            "slug": slugify(c["name"]),
            "region": c.get("region", ""),
            "bestMonths": c.get("bestMonths", []),
            "temp": c.get("temp", ""),
            "emoji": REGION_EMOJI.get(c.get("region", ""), "🌍"),
        })
    INDEX_JSON.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[index] 已生成 {INDEX_JSON}（{len(out)} 城）")

if __name__ == "__main__":
    main()
