import json
import os
import time
import urllib.request
import urllib.parse
from pathlib import Path

ACCESS_KEY = "oY3aQ0bMe8Zdu2MC0iegNRFv-Fr8AeVOwklQXJu0zZI"
BASE_DIR = Path(".")
IMG_DIR = BASE_DIR / "css" / "images"
INDEX_HTML = BASE_DIR / "index.html"
CITIES_JSON = BASE_DIR / "cities.json"

IMG_DIR.mkdir(parents=True, exist_ok=True)

def search_unsplash(query):
    url = f"https://api.unsplash.com/search/photos?query={urllib.parse.quote(query)}&per_page=1&orientation=landscape&client_id={ACCESS_KEY}"
    req = urllib.request.Request(url, headers={"Accept-Version": "v1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            if data.get("results"):
                return data["results"][0]
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print("  [限流] 触发 Unsplash 50次/小时限制，等待 10 分钟...")
            time.sleep(600) # 暂停10分钟
            return search_unsplash(query) # 重试
        else:
            print(f"  [error] 搜索失败: HTTP {e.code}")
    except Exception as e:
        print(f"  [error] 搜索失败: {e}")
    return None

def download_image(url, filepath):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as response, open(filepath, 'wb') as out_file:
            out_file.write(response.read())
        return True
    except Exception as e:
        print(f"  [error] 下载失败: {e}")
        return False

# 读取所有城市
cities = json.loads(CITIES_JSON.read_text(encoding="utf-8"))
attributions = []

print("开始扫描全站图片... 按 Ctrl+C 可随时安全停止，已下载的不会丢。\n")

for city_data in cities:
    city = city_data["name"]
    slug = city.lower().replace(" ", "-").replace("'", "")
    filepath = IMG_DIR / f"{slug}.jpg"
    
    # 1. 断点续传：如果图已经存在，直接跳过
    if filepath.exists():
        print(f"[{city}] 图片已存在，跳过。")
        continue
        
    print(f"[{city}] 正在搜索并下载...")
    photo = search_unsplash(f"{city} city skyline")
    if not photo:
        photo = search_unsplash(city)
        
    if not photo:
        print(f"  -> 找不到 {city} 的图，跳过。")
        continue
        
    img_url = photo["urls"]["regular"]
    author_name = photo["user"]["name"]
    author_link = photo["user"]["links"]["html"]
    
    if download_image(img_url, filepath):
        print(f"  -> 成功保存 {slug}.jpg")
        attributions.append(f"{city}: Photo by <a href='{author_link}?utm_source=travelguides&utm_medium=referral' target='_blank'>{author_name}</a> on <a href='https://unsplash.com/?utm_source=travelguides&utm_medium=referral' target='_blank'>Unsplash</a>")
    else:
        print(f"  -> 下载 {city} 失败。")
        
    # 每次请求后休眠 2 秒，温和抓取
    time.sleep(2)

print("\n[完成] 图片抓取结束！现在自动修改 index.html...")

# 2. 自动修改 index.html 的 JS 渲染逻辑
html_text = INDEX_HTML.read_text(encoding="utf-8")

# 找到所有已下载的图片文件名
downloaded_slugs = [f.stem for f in IMG_DIR.glob("*.jpg")]

js_old = """        function createCityCard(city) {
            return `<a href="cities/${city.slug}.html" class="city-card">
                <div class="city-image">${city.emoji}</div>
                <div class="city-info">
                    <div class="city-name">${city.name}</div>
                    <div class="city-meta">${city.country}</div>
                    <span class="temp-badge">${city.temp}</span>
                </div>
            </a>`;
        }"""

# 如果之前被替换过，要处理旧的代码
import re
js_new = """        const DOWNLOADED_IMAGES = ['""" + "', '".join(downloaded_slugs) + """'];
        function createCityCard(city) {
            const hasImage = DOWNLOADED_IMAGES.includes(city.slug);
            const imgHtml = hasImage 
                ? `<img src="css/images/${city.slug}.jpg" alt="${city.name}" style="width: 100%; height: 140px; object-fit: cover;">`
                : `<div class="city-image">${city.emoji}</div>`;
                
            return `<a href="cities/${city.slug}.html" class="city-card">
                ${imgHtml}
                <div class="city-info">
                    <div class="city-name">${city.name}</div>
                    <div class="city-meta">${city.country}</div>
                    <span class="temp-badge">${city.temp}</span>
                </div>
            </a>`;
        }"""

# 如果之前已经被我们改过，就替换新版
if "const DOWNLOADED_IMAGES" in html_text:
    html_text = re.sub(r'const DOWNLOADED_IMAGES = \[.*?\];.*?function createCityCard[\s\S]*?<\/a>`;\n        }', js_new, html_text)
elif js_old in html_text:
    html_text = html_text.replace(js_old, js_new, 1)

# 3. 自动追加署名
if attributions:
    credits_html = "\n<footer style='text-align: center; padding: 20px; color: #64748b; font-size: 12px;'>\n<p>Photos provided by Unsplash:</p>\n<p>" + " | ".join(attributions) + "</p>\n</footer>\n"
    # 删除旧的 credits 防止重复
    html_text = re.sub(r'<footer style="text-align: center; padding: 20px; color: #64748b; font-size: 12px;">.*?Photos provided by Unsplash.*?</footer>\n?', '', html_text, flags=re.DOTALL)
    if "</body>" in html_text:
        html_text = html_text.replace("</body>", credits_html + "</body>")

INDEX_HTML.write_text(html_text, encoding="utf-8")
print(f"[index.html] 已更新！现在首页将显示 {len(downloaded_slugs)} 个城市的真实图片。")
