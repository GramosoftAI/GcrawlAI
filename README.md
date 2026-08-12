<h3 align="center">
  <a name="readme-top"></a>
  <img
    src="https://gcrawlai.com/Logo.svg"
    height="200"
    alt="GcrawlAI Logo"
  >
</h3>

<div align="center">
  <a href="#">
    <img src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/main/img/mit-license.svg" alt="License" target="_blank">
  </a>
  <a href="https://gcrawl.gramopro.ai/" target="_blank">
    <img src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/main/img/visits.svg" alt="Visit gcrawl.ai">
  </a>
</div>

<div>
  <p align="center">
    <a href="https://x.com/Gramosoftpvtltd?s=20" target="_blank">
      <img src="https://camo.githubusercontent.com/8c6c7b3530573136a2550b2858664b1e2f38d3926e8b844a051f4ec182c99fac/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f466f6c6c6f772532306f6e253230582d3030303030303f7374796c653d666f722d7468652d6261646765266c6f676f3d78266c6f676f3d78266c6f676f436f6c6f723d7768697465" alt="Follow on X" />
    </a>
    <a href="https://www.linkedin.com/showcase/gcrawlai/" target="_blank">
      <img src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/main/img/linked_in.svg" alt="Follow on LinkedIn" />
    </a>
  </p>
</div>

---

## 🤔 Why GcrawlAI?

**GcrawlAI** is a high-performance, enterprise-grade, distributed web crawler, scraper, and extraction platform. Designed to feed retrieval-augmented generation (RAG) pipelines, LLMs, and semantic search indexes, it converts complex, noisy web structures into clean Markdown, structured JSON metadata, and full-page screenshots.

GcrawlAI automates browser steering, stealth obfuscation, anti-bot evasion, and distributed scaling so that you can focus on building AI features rather than managing crawling blockages.

---

## ✨ Features

- **🥷 Fingerprint Hygiene & Stealth Browsing**: Mask automated runtimes, WebGL signatures, canvas fingerprints, and automation leaks to seamlessly bypass aggressive anti-bot protections.
- **🔀 Stepped Residential Proxy Rotation**: Multi-tier automatic proxy escalation with geographic IP targeting matching the target site's local region.
- **✨ Fit-Markdown Extraction**: Converts pages to clean, LLM-ready markdown (pruning HTML boilerplate, menus, footers, and advertisements).
- **💾 Offline HTML Bundle**: Downloads full pages along with CSS, images, and other assets, packaging them into a single ZIP file for local offline rendering.
- **📊 SEO Data Collection**: Automatically extracts metadata, headers, titles, descriptions, open graph tags, and links structure from crawled pages.
- **📸 High-Resolution Screenshotting & Document Parsing**: Physics-based scrolling to capture lazy-loaded content correctly.
- **🗺️ URL Mapping**: `/links` endpoint discovers sitemap/internal links in seconds to build domain crawls.
- **🔎 Unified Search Engine**: Developed a custom router to fetch and process Google search results with automatic search engine fallbacks.
- **📦 Distributed Celery Architecture**: Massively parallel crawling backed by Redis and Celery.
- **⚡ Smart Browser Pooling & Plan-based Concurrency**: Optimized browser resource pooling with dynamic execution concurrency limits enforced based on the user's active subscription plan to guarantee high performance and resource availability.
- **🔒 Production Database Layer**: Secure API key issuance, rate limiting, and PostgreSQL Range Partitioning for search logs.

---

## 🔮 Roadmap / Coming Soon

- **🤖 Extractors (Auto Robots)**: Custom, pre-configured crawling robots designed to scrape and collect data from popular services like **Google Flights**, **Google Maps**, **Justdial**, and others based on specific user requirements.

---

## 📦 Python SDK (`gcrawl_sdk`)

GcrawlAI provides an official, developer-friendly Python SDK (`gcrawl_sdk`) to interact with all API endpoints programmatically.

### Installation

```bash
pip install gcrawl-sdk
```

### Quick Usage Examples

#### 1. Scrape Endpoint (Single Page Extraction)
Converts web pages to clean Markdown, HTML, or JSON.
```python
from gcrawl_sdk import GcrawlClient

client = GcrawlClient(api_key="Your_Gcrawl_APIKey")
result = client.scrape(
    url="https://simplfin.tech",
    formats=["markdown"],
    geo="IN",
    wait=True
)
print(result.markdown)
```

#### 2. Crawl Endpoint (Multi-Page Crawling)
Initiates a deep website crawl up to a specified depth limit.
```python
from gcrawl_sdk import GcrawlClient

client = GcrawlClient(api_key="Your_Gcrawl_APIKey")
result = client.crawl(
    url="https://simplfin.tech",
    limit=50,
    formats=["markdown"],
    geo="IN",
    wait=True
)
for page in result.pages:
    print(f"Page: {page.url}")
    print(page.markdown)
```

#### 3. Links Endpoint (Link Extraction)
Extracts all hyperlinks discovered on a webpage.
```python
from gcrawl_sdk import GcrawlClient

client = GcrawlClient(api_key="Your_Gcrawl_APIKey")
result = client.links(
    url="https://simplfin.tech",
    limit=50,
    geo="default",
    wait=True
)
for link in result.links:
    print(link)
```

#### 4. Screenshot Endpoint (Stealth Captures)
Captures full-page screenshots bypassing lazy-loading limitations.
```python
from gcrawl_sdk import GcrawlClient

client = GcrawlClient(api_key="Your_Gcrawl_APIKey")
result = client.screenshot(
    url="https://simplfin.tech",
    geo="IN",
    wait=True
)
print(result.screenshot_url)
```

#### 5. Search Endpoint (Google Search API)
Queries Google using our unified search engine (utilizing Google search results API, Google Scraper, and DuckDuckGo fallbacks).
```python
from gcrawl_sdk import GcrawlClient

client = GcrawlClient(api_key="Your_Gcrawl_APIKey")
result = client.search(
    query="gramosoft tech",
    limit=10,
    geo="IN"
)
for item in result.results:
    print(f"Rank {item.position}: {item.title} -> {item.url}")
```

---

## 🧭 Feature & API Options Guide

### 1. Scrape API Configuration Options

The `POST /api/v1/scrape` endpoint takes a JSON body specifying the target `url` and optional configurations for output types:

| Object | Field | Default | Description |
|---|---|---|---|
| **proxy** | `geo` | `None` | Country code for proxy routing (e.g. `"US"`, `"IN"`) |
| **markdown** | `enabled` | `False` | Enable extraction of Fit-Markdown output |
| | `clean` | `True` | Strip standard boilerplate nodes (nav, footer, ads) |
| **html** | `enabled` | `False` | Enable raw/cleaned HTML output |
| | `clean` | `True` | Clean HTML content |
| | `remove_external_links` | `False` | Strip outgoing external link tags |
| **screenshot** | `enabled` | `False` | Capture screenshot image |
| | `full_page` | `False` | Capture entire scrolling length of page |
| | `auto_scroll` | `True` | Scroll mimicking human speed to load lazy elements |
| **seo** | `enabled` | `False` | Extract page title, descriptions, open graph tags |

### 2. Batch/Crawl Configuration Options

The `POST /api/v1/crawl` endpoint initiates asynchronous background crawls:

| Field | Default | Description |
|---|---|---|
| `url` | *Required* | Starting homepage or domain URL |
| `crawl.max_pages` | `10` | Hard cap on pages to crawl |
| `crawl.same_domain_only` | `True` | Restrict crawling strictly to base domain |
| `crawl.include_subdomains` | `False` | Expand domain matching to subdomains |

---

## 🛠️ Technology Stack

* **Backend Framework**: [FastAPI](https://github.com/tiangolo/fastapi) (Python 3.9+)
* **Frontend Admin Dashboard**: [Angular](https://github.com/angular/angular)
* **Distributed Task Queue**: [Celery](https://github.com/celery/celery)
* **Cache / Message Broker**: [Redis](https://github.com/redis/redis)
* **Relational Database**: [PostgreSQL](https://www.postgresql.org) (with partitioning and custom indexing)
* **Browser Automation**: [Playwright](https://github.com/microsoft/playwright) (with stealth features)

---

## 📋 Prerequisites

* **Python 3.9+**
* **PostgreSQL** (running on default port 5432)
* **Redis** (running on default port 6379)
* **Git**

### Linux System Dependencies
If you are running on a Linux (Debian/Ubuntu) server, install the following browser runtimes dependencies:
```bash
sudo apt update
sudo apt install -y libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 \
                   libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2t64 \
                   libpangocairo-1.0-0 libgtk-3-0t64
```

---

## ⚙️ Installation

1. **Clone the Repository**
   ```bash
   git clone https://github.com/GramosoftAI/GcrawlAI.git
   cd GcrawlAI
   ```

2. **Create and Activate a Virtual Environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   playwright install
   ```

4. **Configuration Settings**
   * Copy the `.env.example` file to `.env` and fill in your details:
     ```bash
     cp .env.example .env
     ```
   * Ensure `config.yaml` has the correct PostgreSQL database connection details.

5. **Initialize Database Schema**
   Initialize all 19 PostgreSQL tables, indexes, and range partitions, and optionally pre-seed the Evomi and Nodemaven ISP codes:
   ```bash
   python -m api.core.db_setup
   # OR
   python api/core/db_setup.py
   ```

---

## 🚦 Running the Application

For development/production runs, launch the following 4 processes:

**1. Redis Server**
```bash
redis-server
```

**2. Celery Queue Workers**
```bash
# Linux
celery -A web_crawler.crawler.celery_config worker -l info

# Windows
celery -A web_crawler.crawler.celery_config.celery_app worker --loglevel=info --pool=solo
```

**3. Backend FastAPI Server**
```bash
# Development Reload
uvicorn api.api:app --port 8000 --reload

# Production (Multi-workers)
uvicorn api.api:app --host 0.0.0.0 --port 8000 --workers 4 --timeout-keep-alive 120
```
Interactive documentation is served at: `http://localhost:8000/docs`

**4. Frontend Dashboard**
See the [Angular Frontend README](https://github.com/GramosoftAI/GcrawlAI/blob/main/frontend/README.md) for UI build instructions.

---

## 📂 Project Directory Structure

```
.
├── agent/                      # AI Agent planning & extraction
│   ├── core/                   # Agent queue tasks and database access
│   ├── models/                 # State and payload structured models
│   ├── pipeline/               # Planning, search, and scraper orchestration
│   └── services/               # Scraper, search, planner, and LLM providers
├── api/                        # FastAPI Gateway
│   ├── auth/                   # JWT & OTP authentication utilities
│   ├── core/                   # Database pool, payment migrations, db_setup
│   ├── models/                 # Pydantic request & response models
│   ├── routes/                 # REST API & WebSocket routes
│   └── services/               # Queue manager, WebSocket and Email utilities
├── web_crawler/                # Crawler Engine
│   ├── common/                 # Configs, S3 wrappers, proxy and Redis brokers
│   ├── crawler/                # Orchestrators and distributed queues
│   │   ├── helpers/            # Popups removal, captcha bypass, screenshots, SEO
│   │   ├── map/                # Sitemap XML discovery & map crawlers
│   │   └── page/               # Multi-tier page crawlers (1, 2, 3, stealth)
│   └── search/                 # Search engine retrievers
├── scripts/                    # Database ISPs and billing utility scripts
├── config.yaml                 # Core configuration profile
└── requirements.txt            # Python requirements manifest
```

---

## 🔐 Core API Endpoints

* **Scraper & Crawler API**:
  * `POST /api/v1/scrape`: Instant single page rendering & extraction (HTML, Markdown, screenshots, images, SEO).
  * `POST /api/v1/scrape/offline-bundle`: Generate a complete offline package (HTML + css + js + assets inside a ZIP bundle).
  * `POST /api/v1/crawl`: Distributed asynchronous crawling of deep websites.
  * `POST /api/v1/links`: Rapid link mapping of target domains.
  * `POST /api/v1/screenshot`: High-resolution stealth page screenshots.
* **Task & Progress API**:
  * `GET /crawler/status/{job_id}`: Celery task progress lookup.
  * `GET /crawler/data/{job_id}`: Fetch raw JSON result data.
  * `GET /crawler/results/{job_id}`: Poll and fetch completed job data.
  * `GET /crawler/user/{user_id}`: Fetch all crawl job logs for a specific user.

---

## 🤝 Contributing

We welcome community contributions! Please review the following workflow:
1. Fork this repository.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

---

## 📄 License

GcrawlAI is open-source software licensed under the **[MIT License](./LICENSE)**.

<p align="center">
  Built with ❤️ by <a href="https://gramosoft.tech">Gramosoft Private Limited</a>
  <br><br>
  ⭐ If GcrawlAI saves you time, please <strong>star this repo</strong> — it helps others find it!
  <br><br>
  <a href="#readme-top">↑ Back to Top ↑</a>
</p>
