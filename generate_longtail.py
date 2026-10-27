#!/usr/bin/env python3
"""Generate long-tail pages for each city."""

import os
import time
import requests
from pathlib import Path

API_KEY = os.getenv("DEEPSEEK_API_KEY")
API_BASE = "https://api.deepseek.com/v1"

CITIES = [
    "Tokyo", "Kyoto", "Osaka", "Seoul", "Beijing", "Shanghai", "Bangkok", "Singapore", "Bali", "Hanoi",
    "Paris", "London", "Rome", "Barcelona", "Amsterdam", "Vienna", "Prague", "Athens", "Lisbon", "Dublin",
    "New York", "Los Angeles", "San Francisco", "Miami", "Toronto", "Vancouver", "Mexico City", "Rio de Janeiro", "Buenos Aires", "Lima",
    "Sydney", "Melbourne", "Auckland", "Fiji", "Bora Bora",
    "Cairo", "Cape Town", "Marrakech", "Nairobi", "Zanzibar",
    "Dubai", "Istanbul", "Jerusalem", "Petra", "Maldives",
    "Moscow", "St. Petersburg", "Warsaw", "Budapest", "Copenhagen"
]

LONGTAIL_TYPES = [
    {"suffix": "weather", "title": "Weather by Month", "prompt": "monthly weather guide with temperature, rainfall, and best months to visit"},
    {"suffix": "attractions", "title": "Top 10 Attractions", "prompt": "top 10 attractions with descriptions, ticket prices, and visiting tips"},
    {"suffix": "itinerary", "title": "3-Day Itinerary", "prompt": "perfect 3-day itinerary with daily schedules, activities, and restaurant recommendations"},
    {"suffix": "budget", "title": "Travel Cost Guide", "prompt": "complete budget breakdown including accommodation, food, transport, and activities for different travel styles"}
]

def generate_content(city, longtail_type):
    prompt = f"""Write a comprehensive travel guide section for {city}: {longtail_type['prompt']}.

Format as HTML with:
- H2: {city} {longtail_type['title']}
- Introduction paragraph
- Main content (table, list, or structured text)
- Practical tips section

Make it informative, accurate, and helpful for travelers."""

    try:
        response = requests.post(
            f"{API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 2000
            },
            timeout=60
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"Error generating {city} {longtail_type['suffix']}: {e}")
        return None

def create_longtail_page(city, longtail_type, content):
    city_slug = city.lower().replace(" ", "-").replace(".", "")
    filename = f"cities/{city_slug}-{longtail_type['suffix']}.html"
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{city} {longtail_type['title']} - Complete travel guide with practical information for visitors.">
    <title>{city} {longtail_type['title']} | Travel Guides</title>
    <link rel="stylesheet" href="../css/style.css">
</head>
<body>
    <header>
        <nav>
            <a href="../index.html">Home</a> > <a href="{city_slug}.html">{city}</a> > {longtail_type['title']}
        </nav>
    </header>
    
    <main>
        <article>
            {content}
            
            <section class="related-links">
                <h3>More {city} Guides</h3>
                <ul>
                    <li><a href="{city_slug}.html">Best Time to Visit {city}</a></li>
                    <li><a href="{city_slug}-weather.html">{city} Weather</a></li>
                    <li><a href="{city_slug}-attractions.html">{city} Attractions</a></li>
                    <li><a href="{city_slug}-itinerary.html">{city} Itinerary</a></li>
                    <li><a href="{city_slug}-budget.html">{city} Budget</a></li>
                </ul>
            </section>
        </article>
    </main>
    
    <footer>
        <p>&copy; 2026 Travel Guides</p>
    </footer>
</body>
</html>"""
    
    Path(filename).parent.mkdir(parents=True, exist_ok=True)
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Created {filename}")

def update_sitemap():
    pages = ["index.html"]
    
    for city in CITIES:
        city_slug = city.lower().replace(" ", "-").replace(".", "")
        pages.append(f"cities/{city_slug}.html")
        for lt in LONGTAIL_TYPES:
            pages.append(f"cities/{city_slug}-{lt['suffix']}.html")
    
    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n'
    sitemap += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    for page in pages:
        sitemap += f'  <url>\n    <loc>https://yz20260416.github.io/{page}</loc>\n  </url>\n'
    
    sitemap += '</urlset>'
    
    with open('sitemap.xml', 'w') as f:
        f.write(sitemap)
    print("Updated sitemap.xml")

def main():
    print(f"Generating long-tail pages for {len(CITIES)} cities...")
    
    for city in CITIES:
        print(f"\nProcessing {city}...")
        for lt in LONGTAIL_TYPES:
            content = generate_content(city, lt)
            if content:
                create_longtail_page(city, lt, content)
                time.sleep(1)
    
    update_sitemap()
    print("\nDone! All long-tail pages generated.")

if __name__ == "__main__":
    main()