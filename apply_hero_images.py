from pathlib import Path
from city_utils import slugify
import json

cities_dir = Path("cities")
img_dir = Path("css/images")
cities = json.loads(Path("cities.json").read_text(encoding="utf-8"))

fixed = 0
for city_data in cities:
    city = city_data["name"]
    slug = slugify(city)
    img_path = img_dir / f"{slug}.jpg"
    html_file = cities_dir / f"{slug}.html"
    
    if not img_path.exists() or not html_file.exists():
        continue
        
    text = html_file.read_text(encoding="utf-8")
    
    # 检查是否已经加过背景图
    if f"url('../css/images/{slug}.jpg')" in text:
        continue
        
    # 构造 Hero 样式
    hero_style = f"""<style>
    header {{
        background-image: linear-gradient(rgba(0,0,0,0.3), rgba(0,0,0,0.6)), url('../css/images/{slug}.jpg');
        background-size: cover;
        background-position: center;
        color: white;
        padding: 100px 20px;
        border-radius: 12px;
        margin-bottom: 32px;
        text-align: center;
    }}
    header h1 {{ color: white; text-shadow: 0 2px 10px rgba(0,0,0,0.5); font-size: 2.5em; margin-bottom: 12px; }}
    header p {{ color: #f1f5f9; text-shadow: 0 1px 5px rgba(0,0,0,0.5); font-size: 1.1em; line-height: 1.6; max-width: 800px; margin: 0 auto; }}
    </style>
    </head>"""
    
    # 插到 </head> 前面
    if "</head>" in text:
        text = text.replace("</head>", hero_style, 1)
        html_file.write_text(text, encoding="utf-8")
        fixed += 1

print(f"[done] 已给 {fixed} 个城市的主页面加上了全屏 Hero 背景大图。")
