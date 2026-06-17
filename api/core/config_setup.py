import os
import re
import yaml
from pathlib import Path
from web_crawler.common.config import CrawlConfig

_CONFIG = None

def substitute_env_vars(data):
    """
    Recursively substitute environment variables in configuration.
    Supports format: ${VAR_NAME} or ${VAR_NAME:default_value}
    """
    if isinstance(data, dict):
        return {key: substitute_env_vars(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [substitute_env_vars(item) for item in data]
    elif isinstance(data, str):
        # Pattern: ${VAR_NAME} or ${VAR_NAME:default_value}
        def replace_var(match):
            var_name = match.group(1)
            default_value = match.group(2)
            return os.getenv(var_name, default_value or "")
        
        return re.sub(r'\$\{([^:}]+)(?::([^}]*))?\}', replace_var, data)
    else:
        return data

def load_config():
    global _CONFIG
    if _CONFIG is None:
        config_path = "config.yaml"
        # We need to resolve path relative to api.py actually, or assume it's in the root
        BASE_DIR = Path(__file__).resolve().parent.parent.parent
        config_file = BASE_DIR / config_path
        if not config_file.exists():
            config_file = Path(config_path) # fallback
        with open(config_file, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
            # Substitute environment variables
            _CONFIG = substitute_env_vars(raw_config)
    return _CONFIG

def get_db_config():
    config = load_config()
    return config["postgres"]

def setup_crawl_config(payload, default_max_pages=10) -> CrawlConfig:
    # Resolve max pages if crawl options exist
    max_pages = default_max_pages
    if hasattr(payload, 'crawl') and payload.crawl and payload.crawl.max_pages is not None:
        max_pages = payload.crawl.max_pages

    config = CrawlConfig(
        max_pages=max_pages,
        max_workers=4,
        headless=True,
        use_stealth=True
    )

    if getattr(payload, 'proxy', None):
        config.proxy_geo = payload.proxy.geo

    if getattr(payload, 'html', None):
        config.html_clean = payload.html.clean if payload.html.clean is not None else True
        config.html_remove_external_links = payload.html.remove_external_links if payload.html.remove_external_links is not None else False
        config.html_relative_to_absolute_links = payload.html.relative_to_absolute_links if payload.html.relative_to_absolute_links is not None else True
        config.html_remove_data_images = payload.html.remove_data_images if payload.html.remove_data_images is not None else False
        config.html_ignore_tags = payload.html.ignore_tags if payload.html.ignore_tags is not None else []
    else:
        config.html_clean = True
        config.html_remove_external_links = False
        config.html_relative_to_absolute_links = True
        config.html_remove_data_images = False
        config.html_ignore_tags = []

    screenshot_enabled = False
    if getattr(payload, 'screenshot', None):
        config.screenshot_full_page = payload.screenshot.full_page if payload.screenshot.full_page is not None else False
        config.screenshot_format = payload.screenshot.format if payload.screenshot.format is not None else "png"
        config.screenshot_quality = payload.screenshot.quality if payload.screenshot.quality is not None else 90
        screenshot_enabled = payload.screenshot.enabled
        
        config.js_render = payload.screenshot.js_render if payload.screenshot.js_render is not None else False
        fields_set = payload.screenshot.model_fields_set if hasattr(payload.screenshot, 'model_fields_set') else set()
        
        if config.js_render:
            config.render_timeout = payload.screenshot.render_timeout if "render_timeout" in fields_set else 10000
            config.auto_scroll = payload.screenshot.auto_scroll if "auto_scroll" in fields_set else True
            config.scroll_delay = payload.screenshot.scroll_delay if "scroll_delay" in fields_set else 500
            config.max_scrolls = payload.screenshot.max_scrolls if "max_scrolls" in fields_set else 1
        else:
            config.render_timeout = payload.screenshot.render_timeout if "render_timeout" in fields_set else 30000
            config.auto_scroll = payload.screenshot.auto_scroll if "auto_scroll" in fields_set else True
            config.scroll_delay = payload.screenshot.scroll_delay if "scroll_delay" in fields_set else 500
            config.max_scrolls = payload.screenshot.max_scrolls if "max_scrolls" in fields_set else 2

    else:
        config.screenshot_full_page = False
        config.screenshot_format = "png"
        config.screenshot_quality = 90
        config.js_render = False
        config.render_timeout = 30000
        config.auto_scroll = True
        config.scroll_delay = 500
        config.max_scrolls = 2

    if getattr(payload, 'markdown', None):
        config.markdown_clean = payload.markdown.clean if payload.markdown.clean is not None else True
    else:
        config.markdown_clean = True

    return config
