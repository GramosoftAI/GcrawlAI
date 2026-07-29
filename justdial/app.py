import sys
import os

# Ensure the root GcrawlAI path is available and takes precedence over installed site-packages
sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env')))

import streamlit as st
import asyncio
import uuid
import json
import threading
import redis.asyncio as aioredis

# Direct imports instead of hitting the /scrape endpoint
from api.routes.crawler_routes import _run_background_crawl_task
from web_crawler.common.config import CrawlConfig
from api.core.database import _init_db_pool

# Initialize DB pool for the Streamlit process so crawler can persist results
try:
    _init_db_pool()
except Exception as e:
    pass # Pool might already be initialized if Streamlit hot-reloaded

# Configure Streamlit
st.set_page_config(page_title="Directory Search", layout="centered", initial_sidebar_state="expanded")

st.title("Justdial Directory Search")

# Initialize session state
if "listings" not in st.session_state:
    st.session_state.listings = None

if st.session_state.listings:
    st.success(f"Found {len(st.session_state.listings)} business listings!")
    st.subheader("Extracted Business Listings")
    st.json(st.session_state.listings)

with st.form("search_form"):
    col1, col2 = st.columns(2)
    with col1:
        location = st.text_input("Location", placeholder="e.g. Chennai", value="Chennai")
    with col2:
        category = st.text_input("Category", placeholder="e.g. Dentist", value="Dentist")
        
    submitted = st.form_submit_button("Search")

if submitted and location and category:
    st.session_state.listings = None # Reset listings for the new search
    url = f"https://www.justdial.com/{location}/{category}"
    st.info(f"Target URL Generated: {url}")
    
    # User requested configurations
    user_id = 1 # Using 1 for 'Demo' as DB expects an integer
    crawl_id = uuid.uuid4().hex
    
    # Setup crawler configuration matching the previous Justdial settings
    config = CrawlConfig(
        max_pages=1,
        max_workers=1,
        headless=True,
        use_stealth=True,
        proxy_geo="IN",
        js_render=False,
        html_clean = False,
        render_timeout = 30000,
        scroll_delay = 500,
        max_scrolls = 4,
        auto_scroll = True,
        auto_scroll_for_html = True
    )
    
    config.headers = {
        "referer": "https://www.justdial.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"'
    }

    # Wrapper function to match API behavior
    def _wrapper():
        _run_background_crawl_task(
            client_id=crawl_id,
            user_id=user_id,
            start_url=url,
            crawl_mode="single",
            enable_links=True,
            enable_md=True,
            enable_html=True,
            enable_ss=True,
            enable_seo=False,
            enable_images=False,
            config=config
        )

    with st.spinner("Starting crawler in background thread..."):
        try:
            # Run the crawl task in a separate thread so it doesn't block the UI loop
            worker_thread = threading.Thread(target=_wrapper, daemon=True)
            worker_thread.start()
        except Exception as e:
            st.error(f"Failed to submit to background task: {e}")
        
    async def listen_for_updates():
        status_box = st.empty()
        log_box = st.empty()
        data_box = st.empty()
        
        # Subscribe to the crawler's Redis channel directly
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_client = aioredis.from_url(
            redis_url, 
            decode_responses=True,
            health_check_interval=30,
            socket_timeout=300,
            socket_keepalive=True
        )
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"crawl:{crawl_id}")
        
        logs = []
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                    
                data = json.loads(message["data"])
                msg_type = data.get("type")
                
                if msg_type == "log":
                    msg_text = data.get("message", "")
                    logs.append(msg_text)
                    # Keep only last 5 logs for clean UI
                    log_box.code("\n".join(logs[-5:]), language="text")
                        
                elif msg_type == "crawl_completed":
                    status_box.success(f"✅ Success! Crawl ID: `{crawl_id}`")
                    
                    summary_data = data.get("summary", {})
                    
                    listings = summary_data.get("listings")
                    
                    if listings:
                        st.session_state.listings = listings
                        data_box.subheader(f"Extracted Business Listings ({len(listings)})")
                        data_box.json(listings)

                    if listings:
                        st.session_state.needs_rerun = True
                        
                    break
                    
                elif msg_type == "error":
                    status_box.error(f"Error: {data.get('message')}")
                    break
        finally:
            await pubsub.unsubscribe(f"crawl:{crawl_id}")
            await redis_client.aclose()

    # Setup event loop for listening
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Now listen for the results stream
    st.subheader("Live Crawl Progress")
    try:
        loop.run_until_complete(listen_for_updates())
    except Exception as e:
        st.error(f"Failed to stream results: {e}")
        
    if st.session_state.get("needs_rerun"):
        st.session_state.needs_rerun = False
        st.rerun()
