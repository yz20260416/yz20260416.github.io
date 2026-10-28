#!/usr/bin/env python3
"""站点一致性检查：一条命令回答"跑到哪了 / 缺什么 / 多什么 / sitemap对不对"。"""

import json
import re
import sys
from pathlib import Path

from city_utils import slugify, expected_files

ROOT = Path(__file__).parent
CITIES_DIR = ROOT / "cities"
SITEMAP = ROOT / "sitemap.xml"
SITE_BASE_URL = "https://yz20260416.github.io"


def main() -> int:
    data = json.loads((ROOT / "cities.json").read_text(encoding="utf-8"))
    cities = data if isinstance(data, list) else data.get("cities", [])
    problems = 0

    # 0. slug 撞车检查（如 "Xi'an" 和 "Xian" 会撞）
    seen = {}
    for c in cities:
        s = slugify(c["name"])
        if s in seen:
            print(f"[撞车] {seen[s]} 与 {c['name']} 的 slug 都是 '{s}'")
            problems += 1
        seen[s] = c["name"]

    # 1. 每城 5 页是否齐全
    print("== 页面核对 ==")
    total = len(cities) * 5
    existing = 0
    for c in cities:
        missing = [f for f in expected_files(c["name"]) if not (CITIES_DIR / f).exists()]
        if missing:
            print(f"[缺] {c['name']}: {', '.join(missing)}")
            problems += len(missing)
        else:
            existing += 5

    # 2. 孤儿文件：磁盘上有但 cities.json 不认识
    known = {f for c in cities for f in expected_files(c["name"])}
    extras = sorted(p.name for p in CITIES_DIR.glob("*.html") if p.name not in known)
    if extras:
        print(f"[多] 不属于任何城市: {', '.join(extras)}")
        problems += len(extras)

    # 3. sitemap 与实际文件是否一一对应
    print("\n== sitemap 核对 ==")
    disk_urls = {f"{SITE_BASE_URL}/index.html"} | {
        f"{SITE_BASE_URL}/cities/{p.name}" for p in CITIES_DIR.glob("*.html")
    }
    sitemap_urls = set(re.findall(r"<loc>(.*?)</loc>", SITEMAP.read_text(encoding="utf-8"))) if SITEMAP.exists() else set()
    for u in sorted(disk_urls - sitemap_urls):
        print(f"[sitemap 缺] {u}")
        problems += 1
    for u in sorted(sitemap_urls - disk_urls):
        print(f"[sitemap 404] {u}")
        problems += 1

    print(f"\n== 汇总: {len(cities)} 城 | 页面 {existing}/{total} | 问题 {problems} 处 ==")
    print("（生成前的'缺'就是待办清单，属预期；其他类别必须为 0）")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())