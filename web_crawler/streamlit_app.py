import streamlit as st
import requests
import threading
import queue
import json
import time
from websocket import WebSocketApp
from pathlib import Path

# ================= CONFIG =================

API_BASE = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"

# ================= SESSION STATE =================

if "crawl_id" not in st.session_state:
    st.session_state.crawl_id = None

if "messages" not in st.session_state:
    st.session_state.messages = queue.Queue()

if "rendered_files" not in st.session_state:
    st.session_state.rendered_files = set()

# ================= WEBSOCKET THREAD =================

def websocket_listener(crawl_id: str, message_queue: queue.Queue):
    def on_message(ws, message):
        print("📩 WS MESSAGE:", message)

        try:
            data = json.loads(message)
            message_queue.put(data)
        except Exception as e:
            print("❌ WS parse error:", e)

    def on_error(ws, error):
        # Ignore normal close (code 1000)
        if "opcode=8" in str(error) or "1000" in str(error):
            print("🔌 WebSocket closed normally")
        else:
            print("❌ WebSocket error:", error)

    def on_close(ws, close_status_code, close_msg):
        print(f"🔌 WebSocket closed (code={close_status_code})")

    ws = WebSocketApp(
        f"{WS_BASE}/ws/crawl/{crawl_id}",
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    ws.run_forever()

# ================= UI =================

st.title("🕷️ Live Web Crawler (Markdown Streaming)")

with st.form("crawl_form"):
    url = st.text_input("Website URL", placeholder="https://example.com")
    crawl_mode = st.selectbox("Crawl Mode", ["single", "all"])
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        enable_md = st.checkbox("Enable Markdown", value=True)
    with col2:
        enable_html = st.checkbox("Enable HTML", value=False)
    with col3:
        enable_ss = st.checkbox("Enable Screenshot", value=False)
    with col4:
        enable_seo = st.checkbox("Enable SEO", value=False)
        
    submitted = st.form_submit_button("Start Crawl")

if submitted:
    if not url:
        st.error("URL is required")
    else:
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
            st.error(resp.text)
        else:
            data = resp.json()
            st.session_state.crawl_id = data["crawl_id"]

            st.success(f"Crawl started (ID: {st.session_state.crawl_id})")

            # Start WebSocket listener
            ws_thread = threading.Thread(
                target=websocket_listener,
                args=(st.session_state.crawl_id, st.session_state.messages),
                daemon=True,
            )
            ws_thread.start()

# ================= LIVE MARKDOWN RENDER =================

st.markdown("---")
st.subheader("📄 Generated Pages (Markdown)")

# Pull messages from WS queue
while not st.session_state.messages.empty():
    msg = st.session_state.messages.get()

    msg_type = msg.get("type")

    if msg_type == "page_processed":
        url = msg.get("url")
        page_num = msg.get("page")
        title = msg.get("title")
        
        md_file = msg.get("markdown_file")
        html_file = msg.get("html_file")
        ss_file = msg.get("screenshot")
        seo_xlsx = msg.get("seo_xlsx")
        seo_json = msg.get("seo_json")
        seo_md = msg.get("seo_md")
        
        # Unique key for this page render
        page_key = f"{url}_{page_num}"

        # Avoid duplicate renders
        if page_key in st.session_state.rendered_files:
            continue

        st.session_state.rendered_files.add(page_key)

        with st.container():
            st.markdown(f"### Page {page_num} – [{title}]({url})")
            
            # 1. SHOW SCREENSHOT (if enabled/available)
            if ss_file:
                # We can't serve local files directly in Streamlit easily if they aren't static assets.
                # Ideally, we would need an endpoint to serve this image or base64 encode it.
                # For now, we'll just show the path or a placeholder if we can't serve it.
                # IMPROVEMENT: Add an API endpoint to serve artifacts.
                st.info(f"📸 Screenshot saved: `{ss_file}`")

            # 2. SHOW MARKDOWN (if enabled/available)
            if md_file:
                 # 🔥 FETCH RAW MARKDOWN
                md_resp = requests.get(
                    f"{API_BASE}/crawl/get/content",
                    params={"file_path": md_file},
                    timeout=300,
                )

                if md_resp.status_code == 200:
                    markdown_text = md_resp.json().get("markdown", "")
                    with st.expander("Show Markdown Content", expanded=True):
                        st.markdown(markdown_text)
                else:
                    st.error(f"Failed to load markdown: {md_file}")

            # 3. SHOW HTML LINK (if enabled/available)
            if html_file:
                st.success(f"💾 HTML saved: `{html_file}`")
            
            # 4. SHOW SEO XLSX (if enabled/available)
            if seo_xlsx:
                st.success(f"💾 SEO XLSX saved: `{seo_xlsx}`")
            
            # 5. SHOW SEO JSON (if enabled/available)
            if seo_json:
                st.success(f"💾 SEO JSON saved: `{seo_json}`")
            
            # 6. SHOW SEO MD (if enabled/available)
            if seo_md:
                st.success(f"💾 SEO MD saved: `{seo_md}`")

    elif msg_type == "crawl_completed":
        st.success("✅ Crawl completed")

# Allow Streamlit refresh loop
time.sleep(0.3)
st.rerun()
