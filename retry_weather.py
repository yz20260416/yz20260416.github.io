#!/usr/bin/env python3
"""找出降级的天气页（没有 Open-Meteo 标注），只重跑这些城市。"""

import json
import sys
import time
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent
CITIES_DIR = BASE_DIR / "cities"
INDEX_JSON = BASE_DIR / "cities-index.json"
PROBE_URL = "https://geocoding-api.open-meteo.com/v1/search"


def network_ok() -> bool:
    try:
        r = requests.get(PROBE_URL, params={"name": "Tokyo", "count": 1}, timeout=15)
        return r.status_code == 200 and r.json().get("results")
    except Exception:
        return False


def main():
    if not INDEX_JSON.exists():
        print("[error] 缺少 cities-index.json，先跑 build_index.py", file=sys.stderr)
        return 1

    cities = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    slug_to_name = {c["slug"]: c["name"] for c in cities}

    # 找出降级的天气页
    degraded = []
    for f in sorted(CITIES_DIR.glob("*-weather.html")):
        text = f.read_text(encoding="utf-8")
        if "Open-Meteo" not in text:
            slug = f.stem[:-len("-weather")]
            name = slug_to_name.get(slug)
            if name:
                degraded.append(name)

    if not degraded:
        print("[info] 所有天气页都有真实数据，无需重跑。")
        return 0

    print(f"[info] {len(degraded)} 个城市降级: {', '.join(degraded)}\n")

    # 网络探测
    print("[probe] 检查 Open-Meteo 连通性 ...")
    if not network_ok():
        print("[error] Open-Meteo 不可达，请检查网络/代理后重试。", file=sys.stderr)
        return 1
    print("[probe] 连通，开始重跑\n")

    # 构造 --only 参数
    args = []
    for n in degraded:
        args.extend(["--only", n])

    # 连续失败 3 次就停
    fails = 0
    from generate_longtail import main as gen_main
    sys.argv = ["generate_longtail.py", "--type", "weather", "--force"] + args

    # 我们不能直接调 gen_main，因为它会跑完整个 todo；
    # 改为逐个城市调用，方便中途断网时停下
    from generate_longtail import (
        fetch_weather_data, call_deepseek, render_longtail_html,
        CITIES_DATA, CITIES_DIR as CD, longtail_filename, API_KEY,
    )

    ok = 0
    for i, name in enumerate(degraded, 1):
        if not network_ok():
            fails += 1
            print(f"[{i}/{len(degraded)}] {name}: 网络不通，跳过（连续失败 {fails}）")
            if fails >= 3:
                print("[stop] 连续 3 次网络失败，停止。修复网络后重新运行本脚本。")
                return 1
            time.sleep(5)
            continue
        fails = 0

        city_data = next((c for c in CITIES_DATA if c["name"] == name), None)
        if not city_data:
            print(f"[{i}/{len(degraded)}] {name}: 在 cities.json 中找不到，跳过")
            continue

        print(f"[{i}/{len(degraded)}] 重跑 {name} - weather ...")
        try:
            wd = fetch_weather_data(name, city_data.get("country", ""))
            if not wd:
                print(f"  [warn] {name}: 仍拿不到真实数据，跳过")
                time.sleep(3)
                continue
            lt = {"suffix": "weather", "title": "Weather by Month", "prompt": ""}
            content = call_deepseek(name, lt, API_KEY, weather_data=wd)
            html = render_longtail_html(city_data, lt, content, weather_data=wd)
            out = CD / longtail_filename(name, "weather")
            out.write_text(html, encoding="utf-8")
            print(f"  -> 已更新 {out}")
            ok += 1
        except Exception as e:
            print(f"  [error] {name}: {e}", file=sys.stderr)
        time.sleep(3)

    print(f"\n[info] 完成：成功 {ok}/{len(degraded)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
