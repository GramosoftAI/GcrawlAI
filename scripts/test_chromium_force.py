import os
import sys
import logging
from redis import Redis

# Set up logging to console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Resolve baseline path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web_crawler.common.config import CrawlConfig
from web_crawler.crawler.crawler import main as crawl_main

print("\n" + "="*60)
print("FORCE CHROMIUM CRAWL TEST FOR JAPAN AIRLINES (JAL)")
print("="*60)

url = "https://www.jal.co.jp/jp/ja/"

# Clear existing keys in Redis for clean environment
redis_client = Redis.from_url('redis://localhost:6379/0')
redis_client.delete("session:force_chromium_test:chromium:jal.co.jp")
redis_client.delete("session:force_chromium_test:camoufox:jal.co.jp")

# Run config
config = CrawlConfig(
    max_pages=1,
    max_workers=1,
    headless=True,
    use_stealth=True
)
config.js_render = True
config.default_tier = 2 # Use Tier 2 (NodeMaven) which has clean residential IP pool

print(f"\n1. Triggering crawl_main for {url} using Chromium Tier 2...")
result = crawl_main(
    start_url=url,
    enable_md=True,
    enable_html=True,
    enable_ss=False,
    enable_json=False,
    enable_links=False,
    enable_seo=False,
    enable_images=False,
    client_id="force_chromium_test",
    crawl_mode="single",
    config=config
)

print("\n" + "="*60)
print("TEST ANALYSIS")
print("="*60)

# Check Redis keys to confirm which browser actually completed the save
chromium_saved = redis_client.exists("session:force_chromium_test:chromium:jal.co.jp")
camoufox_saved = redis_client.exists("session:force_chromium_test:camoufox:jal.co.jp")

print(f"Pages Crawled: {result.get('pages_crawled')}")
print(f"Pages Failed: {result.get('pages_failed')}")
print(f"Error returned in result: {result.get('error')}")
print(f"HTML Content length: {len(result.get('html_content') or '')}")

if chromium_saved and not camoufox_saved:
    print("\n[SUCCESS] Crawl was successfully completed by CHROMIUM engine!")
    print("No fallback to Camoufox occurred.")
elif camoufox_saved:
    print("\n[WARNING] Fallback to Camoufox occurred. Chromium failed.")
else:
    print("\n[FAIL] Both engines failed to crawl the page.")
