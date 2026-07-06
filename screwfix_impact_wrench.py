#!/usr/bin/env python3
"""
Screwfix Impact Wrench Scraper — 搜尋列表 + 詳情頁規格表
用法:
  python3 screwfix_impact_wrench.py                    # 預設：爬 impact wrench
  python3 screwfix_impact_wrench.py --search "impact ranch"
  python3 screwfix_impact_wrench.py --db impact.db
  python3 screwfix_impact_wrench.py --csv impact.csv
  python3 screwfix_impact_wrench.py --no-details        # 只爬列表，不爬詳情頁

輸出: SQLite + CSV
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
BASE_URL = "https://www.screwfix.com"
SEARCH_URL = f"{BASE_URL}/search"
DEFAULT_DB = "screwfix_impact.db"
DEFAULT_CSV = "screwfix_impact.csv"
DEFAULT_SEARCH = "impact wrench"
PAGE_SIZE = 100
DELAY = 0.5  # 秒，禮貌延遲

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-GB,en;q=0.9",
}

# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def init_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            name TEXT,
            url TEXT,
            image TEXT,
            price REAL,
            currency TEXT,
            rating REAL,
            review_count INTEGER,
            description TEXT,
            brand TEXT,
            model_no TEXT,
            search_query TEXT,
            fetched_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS specs (
            sku TEXT,
            spec_key TEXT,
            spec_value TEXT,
            PRIMARY KEY (sku, spec_key)
        )
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Layer 1: 搜尋列表頁
# ---------------------------------------------------------------------------
def parse_search_page(html: str):
    """從搜尋頁的 LD+JSON ItemList 解析產品"""
    blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    products = []
    for block in blocks:
        try:
            d = json.loads(block)
            if d.get("@type") == "ItemList":
                for item in d.get("itemListElement", []):
                    p = item.get("item", item)
                    offers = p.get("offers", {})
                    rating = p.get("aggregateRating", {})
                    products.append({
                        "sku": p.get("sku", ""),
                        "name": p.get("name", ""),
                        "url": p.get("url", ""),
                        "image": p.get("image", ""),
                        "price": float(offers.get("price", 0)) if offers.get("price") else None,
                        "currency": offers.get("priceCurrency", "GBP"),
                        "rating": float(rating.get("ratingValue", 0)) if rating.get("ratingValue") else None,
                        "review_count": int(rating.get("reviewCount", 0)) if rating.get("reviewCount") else 0,
                        "description": p.get("description", ""),
                    })
                break
        except (json.JSONDecodeError, ValueError):
            continue
    return products


def has_next_page(html: str, current_offset: int) -> bool:
    next_offset = current_offset + PAGE_SIZE
    return bool(re.search(rf"page_start={next_offset}", html))


def scrape_search(search_query: str):
    """爬取所有搜尋列表頁"""
    all_products = []
    offset = 0
    page = 1

    while True:
        params = {
            "search": search_query,
            "page_size": PAGE_SIZE,
            "page_start": offset,
        }
        print(f"  📄 Page {page} (offset={offset})...")
        resp = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()

        products = parse_search_page(resp.text)
        if not products:
            print(f"  ⚠️  No products on page {page}, stopping.")
            break

        all_products.extend(products)
        print(f"     +{len(products)} products (total: {len(all_products)})")

        # Screwfix 可能回傳 99 而不是 100，所以只靠 HTML 連結判斷是否有下一頁
        if not has_next_page(resp.text, offset):
            print(f"  ✅ No more pages.")
            break

        offset += PAGE_SIZE
        page += 1
        time.sleep(DELAY)

    return all_products


# ---------------------------------------------------------------------------
# Layer 2: 產品詳情頁
# ---------------------------------------------------------------------------
def parse_detail_page(html: str):
    """從詳情頁解析 LD+JSON Product + HTML 規格表"""
    result = {
        "brand": None,
        "model_no": None,
        "full_description": None,
        "images": [],
        "specs": {},  # {key: value}
    }

    # LD+JSON Product
    blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    for block in blocks:
        try:
            d = json.loads(block)
            if d.get("@type") == "Product" and d.get("name"):
                brand = d.get("brand", {})
                result["brand"] = brand.get("name", "") if isinstance(brand, dict) else str(brand)
                result["full_description"] = d.get("description", "")
                result["images"] = d.get("image", []) if isinstance(d.get("image"), list) else [d.get("image", "")]
                break
        except (json.JSONDecodeError, ValueError):
            continue

    # HTML 規格表
    tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)
    for table_html in tables:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)
        for row in rows:
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
            clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            clean = [c.replace("&quot;", '"').replace("&amp;", "&").replace("&#39;", "'") for c in clean]
            if len(clean) == 2 and clean[0] != "Specification":
                result["specs"][clean[0]] = clean[1]
                # 提取 model no
                if clean[0].lower() == "model no":
                    result["model_no"] = clean[1]

    return result


def scrape_details(products: list):
    """逐個爬取產品詳情頁"""
    total = len(products)
    for i, p in enumerate(products, 1):
        if not p.get("url"):
            continue
        url = p["url"]
        if not url.startswith("http"):
            url = BASE_URL + url

        print(f"  🔧 [{i}/{total}] {p['sku']}...", end=" ", flush=True)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            detail = parse_detail_page(resp.text)
            p["brand"] = detail["brand"]
            p["model_no"] = detail["model_no"]
            p["full_description"] = detail["full_description"]
            p["specs"] = detail["specs"]
            n_specs = len(detail["specs"])
            print(f"✅ {p['brand']} ({n_specs} specs)")
        except Exception as e:
            print(f"❌ {e}")
            p["brand"] = None
            p["model_no"] = None
            p["full_description"] = p.get("description", "")
            p["specs"] = {}

        time.sleep(DELAY)

    return products


# ---------------------------------------------------------------------------
# 存儲
# ---------------------------------------------------------------------------
def save_to_db(conn, products, search_query):
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    skipped = 0
    for p in products:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO products
                (sku, name, url, image, price, currency, rating, review_count,
                 description, brand, model_no, search_query, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p["sku"], p["name"], p.get("url",""), p.get("image",""),
                p.get("price"), p.get("currency","GBP"), p.get("rating"),
                p.get("review_count",0), p.get("full_description", p.get("description","")),
                p.get("brand"), p.get("model_no"), search_query, now
            ))
            # Specs
            for key, value in p.get("specs", {}).items():
                conn.execute("""
                    INSERT OR REPLACE INTO specs (sku, spec_key, spec_value)
                    VALUES (?, ?, ?)
                """, (p["sku"], key, value))
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1

    conn.commit()
    return inserted, skipped


def save_to_csv(products, csv_path):
    # 收集所有 spec keys
    all_spec_keys = set()
    for p in products:
        all_spec_keys.update(p.get("specs", {}).keys())
    all_spec_keys = sorted(all_spec_keys)

    base_cols = ["sku", "name", "brand", "model_no", "price", "currency",
                 "rating", "review_count", "url", "image"]
    fieldnames = base_cols + all_spec_keys

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for p in products:
            row = {k: p.get(k, "") for k in base_cols}
            for key in all_spec_keys:
                row[key] = p.get("specs", {}).get(key, "")
            writer.writerow(row)

    return len(products)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Screwfix Impact Wrench Scraper")
    parser.add_argument("--search", default=DEFAULT_SEARCH, help="Search query")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite path")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="CSV path")
    parser.add_argument("--no-details", action="store_true", help="Skip detail page scraping")
    args = parser.parse_args()

    t_start = time.time()
    print(f"🔩 Screwfix Impact Wrench Scraper")
    print(f"   Search:  '{args.search}'")
    print(f"   DB:      {args.db}")
    print(f"   CSV:     {args.csv}")
    print(f"   Details: {'skip' if args.no_details else 'fetch'}")
    print()

    # Layer 1: Search
    print("── Layer 1: Search listings ──")
    products = scrape_search(args.search)
    if not products:
        print("❌ No products found.")
        sys.exit(1)
    print(f"\n   Total products found: {len(products)}")

    # Layer 2: Details
    if not args.no_details:
        print("\n── Layer 2: Detail pages (specs) ──")
        products = scrape_details(products)

    # Save
    print("\n── Saving ──")
    conn = init_db(args.db)
    inserted, skipped = save_to_db(conn, products, args.search)
    conn.close()
    print(f"   SQLite: {inserted} inserted/updated, {skipped} skipped → {args.db}")

    csv_count = save_to_csv(products, args.csv)
    print(f"   CSV: {csv_count} rows → {args.csv}")

    elapsed = time.time() - t_start
    print(f"\n✅ Done in {elapsed:.1f}s")

    # Summary
    brands = {}
    for p in products:
        b = p.get("brand") or "Unknown"
        brands[b] = brands.get(b, 0) + 1
    print(f"   Products: {len(products)}")
    print(f"   Brands: {len(brands)}")
    for b, c in sorted(brands.items(), key=lambda x: -x[1]):
        print(f"     {b}: {c}")


if __name__ == "__main__":
    main()