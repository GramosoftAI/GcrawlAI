import streamlit as st
import requests
import threading
import queue
import json
import time
from websocket import WebSocketApp

# ================= PAGE CONFIG =================
st.set_page_config(
    page_title="Live Web Crawler", 
    page_icon="🕷️", 
    layout="wide"
)

# ================= CONFIG =================
API_BASE = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"

# ================= SESSION STATE =================
def init_session_state():
    if "crawl_id" not in st.session_state:
        st.session_state.crawl_id = None
    if "messages" not in st.session_state:
        st.session_state.messages = queue.Queue()
    if "processed_pages" not in st.session_state:
        st.session_state.processed_pages = []  # Store processed pages persistently
    if "is_crawling" not in st.session_state:
        st.session_state.is_crawling = False
    if "urls_seen" not in st.session_state:
        st.session_state.urls_seen = set()
    if "search_results" not in st.session_state:
        st.session_state.search_results = None

init_session_state()

def reset_crawl():
    st.session_state.crawl_id = None
    st.session_state.messages = queue.Queue()
    st.session_state.processed_pages = []
    st.session_state.is_crawling = False
    st.session_state.urls_seen = set()

# ================= WEBSOCKET THREAD =================
def websocket_listener(crawl_id: str, message_queue: queue.Queue):
    def on_message(ws, message):
        try:
            data = json.loads(message)
            message_queue.put(data)
        except Exception as e:
            print("❌ WS parse error:", e)

    def on_error(ws, error):
        if "opcode=8" not in str(error) and "1000" not in str(error):
            print("❌ WebSocket error:", error)

    def on_close(ws, close_status_code, close_msg):
        # Push a final completion message just in case the backend drops connection
        message_queue.put({"type": "crawl_completed"})
        print(f"🔌 WebSocket closed (code={close_status_code})")

    ws = WebSocketApp(
        f"{WS_BASE}/ws/crawl/{crawl_id}",
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    ws.run_forever()

# ================= UI: SIDEBAR CONFIG =================
with st.sidebar:
    action_type = st.selectbox("Action", ["Crawl", "Search"])
    st.divider()

    if action_type == "Crawl":
        st.header("⚙️ Crawl Settings")
        crawl_mode = st.selectbox("Crawl Mode", ["single", "all", "links"], help="Select 'single' for one page or 'all' to spider the site.")
        
        st.subheader("Data Extraction")
        enable_md = st.toggle("Enable Markdown", value=True)
        enable_html = st.toggle("Enable HTML", value=False)
        enable_ss = st.toggle("Enable Screenshot", value=False)
        enable_seo = st.toggle("Enable SEO", value=False)
    else:
        st.header("🔍 Search Settings")
        search_limit = st.slider("Result Limit", min_value=1, max_value=25, value=5)
        
    if st.button("🗑️ Clear History", use_container_width=True):
        reset_crawl()
        st.session_state.search_results = None
        st.rerun()

# ================= UI: MAIN AREA =================
if action_type == "Crawl":
    st.title("🕷️ Live Web Crawler")
    st.markdown("Enter a URL to begin streaming scraped content in real-time.")

    # --- Input Form ---
    with st.form("crawl_form"):
        url = st.text_input("Website URL", placeholder="https://example.com")
        submitted = st.form_submit_button("Start Crawl", type="primary")

    if submitted:
        if not url:
            st.error("URL is required to begin.")
        else:
            reset_crawl() # Clear previous runs
            
            with st.spinner("Initializing crawler..."):
                resp = requests.post(
                    f"{API_BASE}/crawler",
                    json={
                        "url": url, 
                        "crawl_mode": crawl_mode,
                        "enable_md": enable_md,
                        "enable_html": enable_html,
                        "enable_ss": enable_ss,
                        "enable_seo": enable_seo
                    },
                    timeout=300,
                )

                if resp.status_code != 200:
                    st.error(f"Error starting crawl: {resp.text}")
                else:
                    data = resp.json()
                    st.session_state.crawl_id = data["crawl_id"]
                    st.session_state.is_crawling = True

                    # Start WebSocket listener
                    ws_thread = threading.Thread(
                        target=websocket_listener,
                        args=(st.session_state.crawl_id, st.session_state.messages),
                        daemon=True,
                    )
                    ws_thread.start()

elif action_type == "Search":
    st.title("🔍 Web Search")
    st.markdown("Enter a search query to find relevant content.")

    with st.form("search_form"):
        query = st.text_input("Search Query", placeholder="What do you want to find?")
        search_submitted = st.form_submit_button("Search", type="primary")

    if search_submitted:
        if not query:
            st.error("Query is required to search.")
        else:
            with st.spinner("Searching..."):
                try:
                    resp = requests.post(
                        f"{API_BASE}/search",
                        json={"query": query, "limit": search_limit},
                        timeout=60,
                    )
                    if resp.status_code != 200:
                        st.error(f"Error searching: {resp.text}")
                    else:
                        st.session_state.search_results = resp.json()
                except Exception as e:
                    st.error(f"Request failed: {e}")

# ================= PROCESS QUEUE =================
# Pull messages from WS queue and persist them
while not st.session_state.messages.empty():
    msg = st.session_state.messages.get()
    msg_type = msg.get("type")

    if msg_type == "page_processed":
        page_url = msg.get("url")
        # Prevent duplicates
        if page_url not in st.session_state.urls_seen:
            st.session_state.urls_seen.add(page_url)
            
            # Pre-fetch markdown text so we don't do API calls on every st.rerun
            md_file = msg.get("markdown_file")
            markdown_text = "Markdown not enabled or file missing."
            if md_file:
                try:
                    md_resp = requests.get(
                        f"{API_BASE}/crawl/get/content",
                        params={"file_path": md_file},
                        timeout=10,
                    )
                    if md_resp.status_code == 200:
                        markdown_text = md_resp.json().get("markdown", "")
                except Exception as e:
                    markdown_text = f"Failed to fetch markdown: {e}"
            
            # Attach the fetched text to the message payload
            msg["markdown_content"] = markdown_text
            st.session_state.processed_pages.append(msg)

    elif msg_type == "crawl_completed":
        st.session_state.is_crawling = False

# ================= RENDER RESULTS =================
if action_type == "Crawl" and st.session_state.crawl_id:
    st.divider()
    
    # Header & Metrics
    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader(f"📄 Crawl Results")
    with col2:
        st.metric("Pages Processed", len(st.session_state.processed_pages))

    # Active Crawl Indicator
    if st.session_state.is_crawling:
        st.info("🔄 Crawl in progress. Listening for new pages...", icon="⏳")
    elif len(st.session_state.processed_pages) > 0:
        st.success("✅ Crawl completed successfully.", icon="🎉")
    else:
        st.error("❌ Crawl failed: 0 pages processed. The URL may be invalid or blocked the crawler.", icon="🚨")

    # Render all saved pages gracefully
    for page in st.session_state.processed_pages:
        page_num = page.get("page", "?")
        title = page.get("title", "Untitled")
        url = page.get("url", "#")
        
        with st.expander(f"Page {page_num}: {title}", expanded=False):
            st.caption(f"**URL:** [{url}]({url})")
            
            # Use tabs to organize data cleanly
            tab_md, tab_artifacts, tab_seo = st.tabs(["📝 Markdown", "🖼️ Artifacts", "🔍 SEO Files"])
            
            with tab_md:
                st.markdown(page.get("markdown_content", ""))
                
            with tab_artifacts:
                if page.get("screenshot"):
                    st.code(f"Screenshot Path: {page.get('screenshot')}", language="text")
                    st.info("To view images, ensure your API serves static files and map the URL here.")
                if page.get("html_file"):
                    st.success(f"💾 HTML saved: `{page.get('html_file')}`")
                if not page.get("screenshot") and not page.get("html_file"):
                    st.write("No artifacts requested for this page.")
                    
            with tab_seo:
                has_seo = False
                for seo_key in ["seo_xlsx", "seo_json", "seo_md"]:
                    if page.get(seo_key):
                        st.success(f"💾 {seo_key.upper()} saved: `{page.get(seo_key)}`")
                        has_seo = True
                if not has_seo:
                    st.write("SEO generation was not enabled.")

elif action_type == "Search" and st.session_state.search_results:
    st.divider()
    
    data = st.session_state.search_results
    st.subheader("📄 Search Results")
    st.success(f"Found {data.get('count', 0)} results for '{data.get('query', '')}'.")
    
    for item in data.get("results", []):
        with st.container():
            title = item.get("title") or "No Title"
            url = item.get("url") or "#"
            desc = item.get("description") or "No Description"
            
            st.markdown(f"### [{title}]({url})")
            st.markdown(f"**URL:** [{url}]({url})")
            st.write(desc)
            st.divider()

# ================= AUTO-REFRESH LOGIC =================
# Only refresh the app continuously if a crawl is actively happening
if action_type == "Crawl" and st.session_state.is_crawling:
    time.sleep(1) # Slightly longer sleep prevents aggressive UI flickering
    st.rerun()