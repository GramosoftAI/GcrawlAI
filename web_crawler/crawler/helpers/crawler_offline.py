import os
import uuid
import logging
import time
import json
import base64
import io
import zipfile
import re
from urllib.parse import urlparse, urljoin, urlsplit
from datetime import datetime
from typing import Dict, Any, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup
import requests
from web_crawler.crawler.page.page_crawler1 import browser_manager
from web_crawler.common.proxy_manager import ProxyManager
from web_crawler.common.redis_events import publish_event
from api.core.database import get_pooled_connection, upsert_job_result, update_activity_log_status
from web_crawler.common.s3_utils import upload_to_s3

logger = logging.getLogger(__name__)

TRACKER_KEYWORDS = [
    "google-analytics", "googletagmanager", "doubleclick", "facebook.net", 
    "facebook.com/tr", "hotjar", "tiktok.com", "clarity.ms", "mixpanel", 
    "amplitude", "pixel", "pagead", "adnxs", "optimizely", "clarity", "analytics"
]

def is_tracker(url: str) -> bool:
    url_lower = url.lower()
    return any(keyword in url_lower for keyword in TRACKER_KEYWORDS)

def get_extension_from_mime(mime: str, url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    if "." in os.path.basename(path):
        ext = path.split(".")[-1].lower()
        if len(ext) <= 4 and ext.isalnum():
            return ext
            
    mime = mime.split(";")[0].strip().lower()
    mapping = {
        "text/css": "css",
        "text/javascript": "js",
        "application/javascript": "js",
        "application/x-javascript": "js",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/svg+xml": "svg",
        "image/x-icon": "ico",
        "image/vnd.microsoft.icon": "ico",
        "video/mp4": "mp4",
        "video/webm": "webm",
        "audio/mpeg": "mp3",
        "audio/ogg": "ogg",
        "font/woff2": "woff2",
        "font/woff": "woff",
        "font/ttf": "ttf",
        "font/otf": "otf",
        "application/font-woff": "woff",
        "application/font-woff2": "woff2",
        "application/x-font-ttf": "ttf",
    }
    return mapping.get(mime, "bin")

def ensure_asset(url: str, default_type: str, url_to_local_path: Dict[str, str], resources: dict, options: dict) -> Optional[str]:
    if url in url_to_local_path:
        return url_to_local_path[url]
        
    if is_tracker(url):
        return None
        
    # Check options first
    if default_type == "css" and not options.get("css"): return None
    if default_type == "js" and not options.get("js"): return None
    if default_type == "image" and not options.get("images"): return None
    if default_type == "video" and not options.get("media"): return None
    if default_type == "font" and not options.get("fonts"): return None

    if url in resources:
        content_type = resources[url].get("content_type", "").lower()
        ext = get_extension_from_mime(content_type, url)
        
        # Determine actual type based on content-type
        asset_type = default_type
        if "css" in content_type:
            asset_type = "css"
        elif "javascript" in content_type or "ecmascript" in content_type:
            asset_type = "js"
        elif "image" in content_type:
            asset_type = "image"
        elif "video" in content_type or "audio" in content_type:
            asset_type = "video"
        elif "font" in content_type or ext in ["woff", "woff2", "ttf", "eot", "otf"]:
            asset_type = "font"
            
        # Re-check updated type against options
        if asset_type == "css" and not options.get("css"): return None
        if asset_type == "js" and not options.get("js"): return None
        if asset_type == "image" and not options.get("images"): return None
        if asset_type == "video" and not options.get("media"): return None
        if asset_type == "font" and not options.get("fonts"): return None

        # Build clean index-based relative path
        folder_mapping = {
            "css": "css",
            "js": "js",
            "image": "images",
            "video": "video",
            "font": "fonts"
        }
        folder_name = folder_mapping.get(asset_type, "assets")
        index = len([p for p in url_to_local_path.values() if p.startswith(f"{folder_name}/")])
        if asset_type == "css":
            local_path = f"css/style_{index}.css"
        elif asset_type == "js":
            local_path = f"js/script_{index}.js"
        elif asset_type == "image":
            local_path = f"images/image_{index}.{ext}"
        elif asset_type == "video":
            local_path = f"video/media_{index}.{ext}"
        elif asset_type == "font":
            local_path = f"fonts/font_{index}.{ext}"
        else:
            local_path = f"{folder_name}/asset_{index}.{ext}"
            
        url_to_local_path[url] = local_path
        return local_path
        
    return None

def discover_html_assets(html_content: str, base_url: str, options: dict) -> Set[Tuple[str, str]]:
    soup = BeautifulSoup(html_content, "html.parser")
    urls = set()
    
    def add_url(val_str, default_type):
        if not val_str: return
        if default_type == "css" and not options.get("css"): return
        if default_type == "js" and not options.get("js"): return
        if default_type == "image" and not options.get("images"): return
        if default_type == "video" and not options.get("media"): return
        if default_type == "font" and not options.get("fonts"): return

        val_str = val_str.strip()
        if not val_str or val_str.startswith("data:") or val_str.startswith("#") or val_str.startswith("javascript:"):
            return
        abs_url = urljoin(base_url, val_str)
        if not is_tracker(abs_url):
            urls.add((abs_url, default_type))

    # link elements
    for link in soup.find_all("link"):
        rel = [r.lower() for r in link.get("rel", [])]
        if "stylesheet" in rel:
            add_url(link.get("href"), "css")
        elif "icon" in rel or "shortcut" in rel or "apple-touch-icon" in rel:
            add_url(link.get("href"), "image")
        elif "preload" in rel and link.get("as") == "font":
            add_url(link.get("href"), "font")
            
    # script elements
    for script in soup.find_all("script"):
        if script.get("src"):
            add_url(script.get("src"), "js")
            
    # img elements
    for img in soup.find_all("img"):
        if img.get("src"):
            add_url(img.get("src"), "image")
        srcset = img.get("srcset")
        if srcset and options.get("images"):
            for part in srcset.split(","):
                bits = part.strip().split()
                if bits:
                    add_url(bits[0], "image")
                    
    # video, audio, source elements
    for video in soup.find_all("video"):
        if video.get("src"):
            add_url(video.get("src"), "video")
        if video.get("poster"):
            add_url(video.get("poster"), "image")
    for audio in soup.find_all("audio"):
        if audio.get("src"):
            add_url(audio.get("src"), "video")
    for source in soup.find_all("source"):
        if source.get("src"):
            add_url(source.get("src"), "video")
        srcset = source.get("srcset")
        if srcset and options.get("images"):
            for part in srcset.split(","):
                bits = part.strip().split()
                if bits:
                    add_url(bits[0], "image")
                    
    # inline style rules
    for tag in soup.find_all(style=True):
        style = tag.get("style")
        for match in re.finditer(r'url\(\s*([\'"]?)([^\'")\s]+)\1\s*\)', style):
            add_url(match.group(2), "image")
            
    # style blocks
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            for match in re.finditer(r'url\(\s*([\'"]?)([^\'")\s]+)\1\s*\)', style_tag.string):
                url = match.group(2)
                ext = url.split("?")[0].split("#")[0].split(".")[-1].lower()
                add_url(url, "font" if ext in ["woff", "woff2", "ttf", "eot", "otf"] else "image")
            for match in re.finditer(r'@import\s+(?:url\()?([\'"]?)([^\'")]+)\1\)?', style_tag.string):
                add_url(match.group(2), "css")
                
    return urls

def discover_css_assets(css_content: str, css_url: str, options: dict) -> Set[Tuple[str, str]]:
    urls = set()
    
    def add_url(val_str, default_type):
        if not val_str: return
        if default_type == "css" and not options.get("css"): return
        if default_type == "image" and not options.get("images"): return
        if default_type == "font" and not options.get("fonts"): return

        val_str = val_str.strip()
        if not val_str or val_str.startswith("data:") or val_str.startswith("#"):
            return
        abs_url = urljoin(css_url, val_str)
        if not is_tracker(abs_url):
            urls.add((abs_url, default_type))

    # url(...) references
    for match in re.finditer(r'url\(\s*([\'"]?)([^\'")\s]+)\1\s*\)', css_content):
        url = match.group(2)
        ext = url.split("?")[0].split("#")[0].split(".")[-1].lower()
        if ext in ["woff", "woff2", "ttf", "eot", "otf"]:
            add_url(url, "font")
        else:
            add_url(url, "image")
            
    # @import references
    for match in re.finditer(
        r'@import\s+(?:url\()?([\'"]?)([^\'")\s]+)\1\)?|@import\s+([\'"])([^\'"]+)\3|@import\s+([\'"]?)([^\'";\s]+)\5',
        css_content
    ):
        url = match.group(2) or match.group(4) or match.group(6)
        add_url(url, "css")
        
    return urls

def rewrite_css(css_content: str, css_url: str, url_to_local_path: Dict[str, str], resources: dict, options: dict) -> str:
    def replace_url(match):
        quote = match.group(1) or ""
        raw_url = match.group(2).strip()
        
        if not raw_url or raw_url.startswith("data:") or raw_url.startswith("#") or raw_url.startswith("http://localhost") or raw_url.startswith("https://localhost"):
            return match.group(0)
            
        try:
            abs_url = urljoin(css_url, raw_url)
            local_path = ensure_asset(abs_url, "image", url_to_local_path, resources, options)
            if local_path:
                if local_path.startswith("css/"):
                    rel_path = local_path[4:]
                else:
                    rel_path = "../" + local_path
                return f"url({quote}{rel_path}{quote})"
        except Exception as e:
            logger.debug(f"Failed to rewrite CSS url reference {raw_url} inside {css_url}: {e}")
            
        return match.group(0)

    css_content = re.sub(r'url\(\s*([\'"]?)([^\'")\s]+)\1\s*\)', replace_url, css_content)
    
    def replace_import(match):
        raw_url = match.group(2) or match.group(4) or match.group(6)
        raw_url = raw_url.strip()
        quote = match.group(1) or match.group(3) or match.group(5) or '"'
        
        if not raw_url or raw_url.startswith("data:"):
            return match.group(0)
            
        try:
            abs_url = urljoin(css_url, raw_url)
            local_path = ensure_asset(abs_url, "css", url_to_local_path, resources, options)
            if local_path:
                if local_path.startswith("css/"):
                    rel_path = local_path[4:]
                else:
                    rel_path = "../" + local_path
                return f'@import {quote}{rel_path}{quote}'
        except Exception as e:
            logger.debug(f"Failed to rewrite CSS @import reference {raw_url}: {e}")
            
        return match.group(0)
        
    css_content = re.sub(
        r'@import\s+(?:url\()?([\'"]?)([^\'")]+)\1\)?|@import\s+([\'"])([^\'"]+)\3|@import\s+([\'"]?)([^\'";\s]+)\5',
        replace_import,
        css_content
    )
    return css_content

def rewrite_html_bs4(html_content: str, base_url: str, url_to_local_path: Dict[str, str], resources: dict, options: dict) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    
    def rewrite_attr(tag, attr, default_type):
        val = tag.get(attr)
        if not val:
            return
            
        val_str = str(val).strip()
        if not val_str or val_str.startswith("data:") or val_str.startswith("#") or val_str.startswith("javascript:"):
            return
            
        abs_url = urljoin(base_url, val_str)
        local_path = ensure_asset(abs_url, default_type, url_to_local_path, resources, options)
        if local_path:
            tag[attr] = local_path

    # Process links (stylesheets, icons, preloads)
    for link in soup.find_all("link"):
        rel = [r.lower() for r in link.get("rel", [])]
        if "stylesheet" in rel:
            rewrite_attr(link, "href", "css")
        elif "icon" in rel or "shortcut" in rel or "apple-touch-icon" in rel:
            rewrite_attr(link, "href", "image")
        elif "preload" in rel and link.get("as") == "font":
            rewrite_attr(link, "href", "font")
            
    # Process scripts
    for script in soup.find_all("script"):
        if script.get("src"):
            rewrite_attr(script, "src", "js")
            
    # Process images
    for img in soup.find_all("img"):
        rewrite_attr(img, "src", "image")
        srcset = img.get("srcset")
        if srcset and options.get("images"):
            new_srcset_parts = []
            for part in srcset.split(","):
                bits = part.strip().split()
                if not bits: continue
                img_url = bits[0]
                abs_url = urljoin(base_url, img_url)
                local_path = ensure_asset(abs_url, "image", url_to_local_path, resources, options)
                if local_path:
                    new_srcset_parts.append(f"{local_path} {' '.join(bits[1:])}")
                else:
                    new_srcset_parts.append(part.strip())
            img["srcset"] = ", ".join(new_srcset_parts)
            
    # Process media
    for video in soup.find_all("video"):
        rewrite_attr(video, "src", "video")
        rewrite_attr(video, "poster", "image")
    for audio in soup.find_all("audio"):
        rewrite_attr(audio, "src", "video")
    for source in soup.find_all("source"):
        rewrite_attr(source, "src", "video")
        srcset = source.get("srcset")
        if srcset and options.get("images"):
            new_srcset_parts = []
            for part in srcset.split(","):
                bits = part.strip().split()
                if not bits: continue
                img_url = bits[0]
                abs_url = urljoin(base_url, img_url)
                local_path = ensure_asset(abs_url, "image", url_to_local_path, resources, options)
                if local_path:
                    new_srcset_parts.append(f"{local_path} {' '.join(bits[1:])}")
                else:
                    new_srcset_parts.append(part.strip())
            source["srcset"] = ", ".join(new_srcset_parts)

    # Process inline styles
    for tag in soup.find_all(style=True):
        style = tag.get("style")
        if "url(" in style:
            tag["style"] = rewrite_css(style, base_url, url_to_local_path, resources, options)

    # Process embedded style tags
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            new_style = rewrite_css(style_tag.string, base_url, url_to_local_path, resources, options)
            style_tag.string.replace_with(new_style)

    return str(soup)

def generate_offline_bundle(
    crawl_id: str,
    url: str,
    html: bool,
    css: bool,
    js: bool,
    images: bool,
    media: bool,
    fonts: bool,
    user_id: Any,
    config: Any
):
    start_time = time.time()
    logger.info(f"Starting offline bundle extraction for crawl_id: {crawl_id}, url: {url}")
    update_activity_log_status(crawl_id, "RUNNING")
    
    options = {
        "html": html,
        "css": css,
        "js": js,
        "images": images,
        "media": media,
        "fonts": fonts
    }
    
    # Load attempt order from environment with default fallback values
    attempt_1 = os.getenv("ATTEMPT_1", "nodemaven").strip().lower()
    attempt_2 = os.getenv("ATTEMPT_2", "thordata").strip().lower()
    attempt_3 = os.getenv("ATTEMPT_3", "evomi_core").strip().lower()

    provider_names = {
        "thordata": "Thordata",
        "nodemaven": "Nodemaven",
        "evomi_core": "Evomi Core"
    }

    # Normalize configured providers from environment
    configured_pids = []
    for pid in [attempt_1, attempt_2, attempt_3]:
        if pid and pid in provider_names:
            configured_pids.append(pid)
    if not configured_pids:
        configured_pids = ["nodemaven", "thordata", "evomi_core"]

    providers = []
    for pid in configured_pids:
        p_name = provider_names[pid]
        providers.append((p_name, pid))
    
    proxy_manager = ProxyManager()
    local_data = browser_manager._get_local_data()
    v_width = getattr(local_data, "width", 1920)
    v_height = getattr(local_data, "height", 1080)
    
    # Initialize variables that must persist outside the attempt loop
    page = None
    context = None
    resources = {}
    success = False
    last_error = None
    live_html = None
    proxy_settings = None
    proxy_usage = {}
    import threading
    bandwidth_lock = threading.Lock()

    for idx, (provider_name, provider_id) in enumerate(providers):
        attempt = idx + 1
        logger.info(f"Attempt {attempt}/{len(providers)} - Provider: {provider_name} for URL: {url}")
        
        # 1. Resolve proxy settings
        use_high_speed = (provider_id in {"nodemaven"})
        proxy_settings = proxy_manager.get_playwright_proxy(
            target_url=url,
            provider=provider_id,
            use_high_speed=use_high_speed,
            proxy_geo=config.proxy_geo
        )
        if not proxy_settings:
            raise RuntimeError(f"Proxy credentials not found or failed to resolve for provider: {provider_name}")
            
        # 2. Launch browser & context
        try:
            browser = browser_manager.get_clock_browser(config, direct=False)
            
            context_kwargs = dict(
                viewport={"width": v_width, "height": v_height},
                java_script_enabled=True,
                ignore_https_errors=True
            )
            if proxy_settings:
                context_kwargs["proxy"] = proxy_settings
                
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            
            # Setup response listener
            resources.clear()
            bandwidth_bytes = [0]
            
            def handle_response(response):
                try:
                    r_url = response.url
                    if r_url.startswith("data:"): return
                    body = response.body()
                    resources[r_url] = {
                        "bytes": body,
                        "content_type": response.headers.get("content-type", "")
                    }
                    with bandwidth_lock:
                        bandwidth_bytes[0] += len(body)
                except Exception:
                    pass
                    
            page.on("response", handle_response)
            
            nav_timeout = 45000
            
            logger.info(f"Navigating page using {provider_name} (timeout={nav_timeout}ms): {url}")
            page.goto(url, wait_until="load", timeout=nav_timeout)
            
            # Smooth scroll
            page.wait_for_timeout(2000)
            scroll_height = page.evaluate("document.body.scrollHeight")
            viewport_height = page.evaluate("window.innerHeight")
            
            current_scroll = 0
            scroll_steps = 5
            for _ in range(scroll_steps):
                current_scroll += viewport_height
                if current_scroll > scroll_height:
                    break
                page.evaluate(f"window.scrollTo(0, {current_scroll})")
                page.wait_for_timeout(1000)
                
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
            
            # Check for Cloudflare/WAF block or CAPTCHA pages
            from web_crawler.crawler.helpers.crawler_captcha import is_captcha_page
            if is_captcha_page(page):
                raise RuntimeError(f"WAF Block / CAPTCHA challenge wall detected this site!")
                
            from web_crawler.crawler.helpers.crawler_helpers import safe_get_content
            live_html = safe_get_content(page)
            success = True
            logger.info(f"✓ Page loaded successfully using {provider_name}!")
            proxy_usage[provider_id] = bandwidth_bytes[0]
            break
            
        except Exception as err:
            logger.warning(f"Attempt {attempt}/{len(providers)} using {provider_name} failed: {err}")
            last_error = err
            proxy_usage[provider_id] = bandwidth_bytes[0] if 'bandwidth_bytes' in locals() else 0
            # Close page/context immediately so they don't leak
            try: page.close()
            except: pass
            try: context.close()
            except: pass
            page = None
            context = None

    if not success:
        if last_error:
            raise last_error
        else:
            raise RuntimeError("All proxy attempts and direct connection failed.")
            
    try:
        
        # --- OPTIMIZED PARALLEL PRE-FETCHING ---
        # 1. Discover all assets from DOM HTML first
        discovered_urls = discover_html_assets(live_html, url, options)
        
        # Configure Requests Session with same proxy
        session = requests.Session()
        if proxy_settings:
            server = proxy_settings.get("server", "")
            if not server.startswith("http"):
                server = "http://" + server
            parsed = urlsplit(server)
            username = proxy_settings.get("username", "")
            password = proxy_settings.get("password", "")
            if username and password:
                proxy_url = f"http://{username}:{password}@{parsed.netloc}"
            else:
                proxy_url = f"http://{parsed.netloc}"
            session.proxies = {"http": proxy_url, "https": proxy_url}
            
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

        def download_single_asset(asset_url_type):
            asset_url, asset_type = asset_url_type
            if asset_url in resources or is_tracker(asset_url):
                return
            try:
                res = session.get(asset_url, timeout=5)
                if res.status_code == 200:
                    resources[asset_url] = {
                        "bytes": res.content,
                        "content_type": res.headers.get("content-type", "")
                    }
                    with bandwidth_lock:
                        bandwidth_bytes[0] += len(res.content)
            except Exception:
                pass

        # Fetch DOM assets in parallel
        logger.info(f"Parallel fetching {len(discovered_urls)} assets from HTML...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(download_single_asset, list(discovered_urls))
            
        # 2. Discover sub-assets inside downloaded CSS files
        discovered_css_urls = set()
        for asset_url, data in list(resources.items()):
            content_type = data.get("content_type", "").lower()
            if "css" in content_type:
                try:
                    css_text = data["bytes"].decode("utf-8", errors="ignore")
                    sub_assets = discover_css_assets(css_text, asset_url, options)
                    discovered_css_urls.update(sub_assets)
                except Exception:
                    pass
                    
        # Fetch CSS sub-assets in parallel
        if discovered_css_urls:
            logger.info(f"Parallel fetching {len(discovered_css_urls)} sub-assets from CSS stylesheets...")
            with ThreadPoolExecutor(max_workers=10) as executor:
                executor.map(download_single_asset, list(discovered_css_urls))
                
        # --- END OPTIMIZED PRE-FETCHING ---

        # Update successful provider's bandwidth with pre-fetched asset bytes
        proxy_usage[provider_id] = bandwidth_bytes[0]

        url_to_local_path = {}
        
        logger.info("Rewriting HTML and stylesheet references in memory...")
        # Since all assets are pre-fetched in resources, ensure_asset will never block or call get()!
        rewritten_html = rewrite_html_bs4(live_html, url, url_to_local_path, resources, options)
        
        # Rewrite CSS content
        css_files = [u for u, p in url_to_local_path.items() if p.startswith("css/")]
        rewritten_css_files = {}
        for css_url in css_files:
            local_path = url_to_local_path[css_url]
            res_data = resources.get(css_url)
            if res_data:
                try:
                    css_text = res_data["bytes"].decode("utf-8", errors="ignore")
                    new_css_text = rewrite_css(css_text, css_url, url_to_local_path, resources, options)
                    rewritten_css_files[local_path] = new_css_text.encode("utf-8")
                except Exception as e:
                    logger.error(f"Failed to rewrite CSS at {css_url}: {e}")
                    
        # Package ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            if html:
                zip_file.writestr("index.html", rewritten_html.encode("utf-8"))
                
            for local_path, css_bytes in rewritten_css_files.items():
                zip_file.writestr(local_path, css_bytes)
                
            for asset_url, local_path in url_to_local_path.items():
                if local_path.startswith("css/"):
                    continue
                res_data = resources.get(asset_url)
                if res_data and res_data.get("bytes"):
                    zip_file.writestr(local_path, res_data["bytes"])
                    
        zip_bytes = zip_buffer.getvalue()
        logger.info(f"✓ Offline ZIP File compiled in-memory. Size: {len(zip_bytes)} bytes.")
        
        # Upload individual assets and final ZIP to S3
        s3_assets = []
        for asset_url, local_path in url_to_local_path.items():
            res_data = resources.get(asset_url)
            if res_data and res_data.get("bytes"):
                c_type = res_data.get("content_type", "application/octet-stream")
                filename = os.path.basename(local_path)
                
                if local_path.startswith("images/") or local_path.startswith("video/"):
                    s3_url = upload_to_s3(res_data["bytes"], crawl_id, filename, c_type)
                    if s3_url:
                        s3_assets.append({
                            "original_url": asset_url,
                            "local_path": local_path,
                            "s3_url": s3_url,
                            "size": len(res_data["bytes"])
                        })
                        
        zip_filename = f"{urlparse(url).netloc.replace('www.', '').replace('.', '_')}_offline.zip"
        zip_s3_url = upload_to_s3(zip_bytes, crawl_id, zip_filename, "application/zip")
        logger.info(f"Uploaded ZIP file to S3: {zip_s3_url}")
        
        elapsed = time.time() - start_time
        time_taken_str = f"{elapsed:.2f}s"
        
        save_payload = {
            "crawl_id": crawl_id,
            "start_url": url,
            "pages_crawled": 1,
            "pages_failed": 0,
            "started_at": datetime.now().isoformat(),
            "crawl_mode": "offline-bundle",
            "zip_s3_url": zip_s3_url,
            "files_count": len(url_to_local_path) + (1 if html else 0),
            "zip_size_bytes": len(zip_bytes),
            "assets_meta": s3_assets,
            "proxy_usage": proxy_usage,
            "time_taken": time_taken_str
        }
        
        upsert_job_result(crawl_id, save_payload, str(user_id) if user_id else None)
        update_activity_log_status(crawl_id, "COMPLETED")
        
        try:
            from api.core.database import update_activity_log_time
            update_activity_log_time(crawl_id, time_taken_str)
        except Exception as time_err:
            logger.error(f"Failed to update activity log time: {time_err}")
            
        with get_pooled_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE crawl_jobs SET updated_at = %s WHERE crawl_id = %s",
                (datetime.now(), crawl_id)
            )
            conn.commit()
            cur.close()
            
        # Log bandwidth to DB
        try:
            from api.core.database import log_proxy_bandwidth
            log_proxy_bandwidth(
                user_id=user_id if user_id else 1,
                endpoint="OFFLINE_BUNDLE",
                url_or_query=url,
                bandwidth_data=proxy_usage,
                status="success",
                job_id=crawl_id
            )
            logger.info(f"✓ Logged proxy bandwidth for job_id: {crawl_id} - {proxy_usage}")
        except Exception as bw_err:
            logger.error(f"Failed to log proxy bandwidth for offline-bundle: {bw_err}")

        publish_event(
            crawl_id=crawl_id,
            payload={
                "type": "crawl_completed",
                "status": "COMPLETED",
                "summary": {
                    "status": "completed",
                    "crawl_id": crawl_id,
                    "zip_s3_url": zip_s3_url,
                    "proxy_usage": proxy_usage,
                    "time_taken": time_taken_str
                }
            }
        )
        logger.info(f"Published complete event to WebSocket for crawl_id: {crawl_id}")
        
    except Exception as e:
        logger.error(f"Offline bundle scraping failed: {e}", exc_info=True)
        update_activity_log_status(crawl_id, "FAILED")
        
        # Calculate time taken on failure
        elapsed = time.time() - start_time
        time_taken_str = f"{elapsed:.2f}s"
        try:
            from api.core.database import update_activity_log_time
            update_activity_log_time(crawl_id, time_taken_str)
        except Exception as time_err:
            logger.error(f"Failed to update activity log time on failure: {time_err}")
            
        # Log failure to crawl_errors table for overall logs
        try:
            with get_pooled_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO crawl_errors (crawl_id, url, error_source, reason, blocked_message, user_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (crawl_id, url, "Offline Bundle Scraper", str(e), str(e), str(user_id) if user_id else "1")
                    )
                conn.commit()
            logger.info(f"✓ Recorded offline-bundle error in crawl_errors for: {crawl_id}")
        except Exception as ce_err:
            logger.warning(f"⚠ Could not write to crawl_errors: {ce_err}")

        # Log failure to admin_error_logs table
        try:
            from api.core.admin_logger import log_admin_error
            import traceback
            
            domain = urlparse(url).netloc
            error_type = type(e).__name__
            stack_trace = traceback.format_exc()
            request_params = {
                "url": url,
                "html": html,
                "css": css,
                "js": js,
                "images": images,
                "media": media,
                "fonts": fonts
            }
            proxy_ip_str = "No Proxy Active"
            if 'proxy_settings' in locals() and proxy_settings:
                proxy_ip_str = f"{proxy_settings.get('server')} ({proxy_settings.get('username')})"
                
            log_admin_error(
                log_id=crawl_id,
                source_tool="Offline Bundle",
                target_domain=domain,
                error_type=error_type,
                severity="Error",
                error_details=str(e),
                request_params=request_params,
                stack_trace=stack_trace,
                proxy_ip=proxy_ip_str,
                user_id=str(user_id) if user_id else "1"
            )
            logger.info(f"✓ Logged failure to admin_error_logs for crawl_id: {crawl_id}")
        except Exception as log_err:
            logger.warning(f"⚠ Could not write to admin_error_logs: {log_err}")

        publish_event(
            crawl_id=crawl_id,
            payload={
                "type": "crawl_failed",
                "status": "FAILED",
                "error": str(e),
                "time_taken": time_taken_str
            }
        )
    finally:
        try:
            page.close()
            context.close()
        except Exception:
            pass
