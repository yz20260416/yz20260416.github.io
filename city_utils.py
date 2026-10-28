"""slug 的唯一权威定义。所有脚本必须从这里 import，禁止各自实现。"""

import re

LONGTAIL_SUFFIXES = ("weather", "attractions", "itinerary", "budget")


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def city_filename(name: str) -> str:
    return f"{slugify(name)}.html"


def longtail_filename(name: str, suffix: str) -> str:
    return f"{slugify(name)}-{suffix}.html"


def expected_files(name: str) -> list[str]:
    """一座城应拥有的全部 5 个页面文件名。"""
    return [city_filename(name)] + [longtail_filename(name, s) for s in LONGTAIL_SUFFIXES]