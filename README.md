<h3 align="center">
  <a name="readme-top"></a>
  <img
    src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/main/img/Crawl%20Logo.svg"
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
      <img src="https://camo.githubusercontent.com/8c6c7b3530573136a2550b2858664b1e2f38d3926e8b844a051f4ec182c99fac/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f466f6c6c6f772532306f6e253230582d3030303030303f7374796c653d666f722d7468652d6261646765266c6f676f3d78266c6f676f436f6c6f723d7768697465" alt="Follow on X" />
    </a>
    <a href="https://www.linkedin.com/showcase/gcrawlai/" target="_blank">
      <img src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/main/img/linked_in.svg" alt="Follow on LinkedIn" />
    </a>
  </p>
</div>

---

## 🚀 Welcome to GcrawlAI
**GcrawlAI** is a high-performance, enterprise-grade distributed web crawler, scraper, and AI-agent extraction platform. Designed to feed retrieval-augmented generation (RAG) pipelines, LLMs, and semantic search indexes, it converts complex, noisy web structures into clean Markdown, structured JSON metadata, and full-page screenshots.

GcrawlAI automates browser steering, stealth obfuscation, anti-bot evasion, and distributed scaling so that you can focus on building AI features rather than managing crawling blockages.

---

## ✨ Core Platforms & Modules

### 1. 🥷 Anti-Bot Evasion & Stealth Crawling Engine
Built directly into the core browser stack, GcrawlAI implements state-of-the-art fingerprint evasion techniques:
* **CloakBrowser & Custom Stealth Drivers**: Seamless integration with premium browser stealth extensions to mask automated runtimes, user-agents, canvas fingerprints, and WebGL signatures.
* **Stepped Residential Proxy Rotation**: Multi-tier automatic proxy escalation (`Evomi Premium` ➔ `Nodemaven` ➔ `Evomi Core`). It leverages geo-IP targeting to match the site's local region and dynamically generates clean residential ISP sessions.
* **Cinematic Human-Like Auto-Scrolling**: A physics-based, constant-speed scroll mechanism (`600px/second` or `24px` increments at `40ms` / 25 FPS) mimicking real human reading trajectories. It budgets and waits for the full configured `scroll_delay` between steps to force lazy-loaded images, assets, and scripts to initialize without causing blur or motion glitches in screenshots.
* **Automated Interaction & Bypass**: Proactively cleans and closes cookie consent banners, popups, and screen overlays before taking screenshots or processing HTML to ensure a clean capture.

### 2. 🤖 LLM-Powered Agentic Extraction Pipeline
For highly ambiguous or dynamic tasks, GcrawlAI features a complete multi-step agentic search and extraction system:
* **LLM Planner & Reasoner**: Utilizing state-of-the-art models (GPT-4o, Claude 3.5 Sonnet) to analyze user extraction schemas and plan query strategies.
* **Autonomous Web Search**: Resolves relevant content in real-time utilizing integrations like Tavily, DuckDuckGo, and SerpAPI.
* **Semantic Extractor**: Parses scraped page content into custom schemas, converting raw, unstructured HTML into clean, validated JSON output.
* **Credit Billing system**: Built-in billing metrics to calculate exact token usage, search operations, and scraping queries, deducting credits relative to plan structures.

### 3. 📦 Distributed Scale Crawling Engine
For large-scale, full-site crawling:
* **Celery Task Queue**: Out-of-the-box parallel crawling using Celery backed by Redis.
* **Sitemap XML Parsing**: Automated discovery of sitemaps to map and scrape thousands of internal URLs rapidly.
* **AWS S3 / Cloud Artifact Storage**: Automatically uploads HTML outputs, screenshots, and metadata to cloud object storage.
* **Real-time Live Progress tracking**: Streams real-time progress indicators, title updates, and page metrics back to the client via WebSockets.

### 4. 🔒 Enterprise Auth, Pricing & Billing API
A complete, production-ready SaaS administration layer:
* **FastAPI Gateways**: Secure API key issuance, rate limiting, and route security.
* **User Authentication**: JWT-based security flow coupled with reliable SMTP Email OTP verification for signups and password resets.
* **Subcription Pricing Plans**: Pre-built plans (Free, Starter, Growth, Pro) integrated with Stripe payments, plan expiry dates, usage tracking, and concurrency limits.
* **PostgreSQL Range Partitioning**: `job_results` table is range partitioned daily to support rapid queries and autovacuum performance under high-concurrency loads.

---

## 🛠️ Technology Stack

* **Backend Framework**: [FastAPI](https://github.com/tiangolo/fastapi) (Python 3.9+)
* **Frontend Admin Dashboard**: [Angular](https://github.com/angular/angular)
* **Distributed Task Queue**: [Celery](https://github.com/celery/celery)
* **Cache / Message Broker**: [Redis](https://github.com/redis/redis)
* **Relational Database**: [PostgreSQL](https://www.postgresql.org) (with partitioning and custom indexing)
* **Browser Automation**: [Playwright](https://github.com/microsoft/playwright) / CloakBrowser
* **AI Framework & LLMs**: OpenAI GPT, Anthropic Claude

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
│   │   └── page/               # Multi-tier page crawlers (1, 2, 3, Cloak)
│   └── search/                 # Search engine retrievers
├── scripts/                    # Database ISPs and billing utility scripts
├── config.yaml                 # Core configuration profile
└── requirements.txt            # Python requirements manifest
```

---

## 🔐 Core API Endpoints

* **Scraper & Crawler API**:
  * `POST /api/v1/scrape`: Instant single page rendering & extraction (HTML, Markdown, screenshots, images, SEO).
  * `POST /api/v1/crawl`: Distributed asynchronous crawling of deep websites.
  * `POST /api/v1/links`: Rapid link mapping of target domains.
  * `POST /api/v1/screenshot`: High-resolution stealth page screenshots.
  * `GET /crawler/status/{task_id}`: Celery task progress lookup.
  * `GET /crawler/data/{crawl_id}`: Fetch crawled output results.
  * `GET /crawl/get/content`: Fetch parsed HTML/Markdown artifacts.
* **AI Agent API**:
  * `POST /api/v1/agent`: Launch an asynchronous schema-driven extraction job.
  * `GET /api/v1/agent/{job_id}`: Lookup agent execution status & results.
  * `DELETE /api/v1/agent/{job_id}`: Cancel a running agent pipeline.
* **SaaS Auth API**:
  * `POST /api/v1/auth/signup/send-otp`: Dispatches validation code to sign up.
  * `POST /api/v1/auth/signup/verify-otp`: Confirms validation and activates account.
  * `POST /api/v1/auth/signin`: Validates credentials and returns JWT bearer token.
  * `POST /api/v1/auth/forgot-password` / `/reset-password`: Account recovery endpoints.

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
