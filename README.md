<h3 align="center">
  <a name="readme-top"></a>
  <img
    src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/dev/feature/img/Crawl%20Logo.svg"
    height="200"
  >
</h3>

<div align="center">
  <a href="#">
    <img src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/dev/feature/img/license.svg" alt="License">
  </a>
  <a href="#">
    <img src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/dev/feature/img/downloads.svg" alt="Downloads">
  </a>
  <a href="#">
    <img src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/dev/feature/img/contributors.svg" alt="GitHub Contributors">
  </a>
  <a href="https://gcrawl.gramopro.ai/">
    <img src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/dev/feature/img/visits.svg" alt="Visit gcrawl.ai">
  </a>
</div>

<div>
  <p align="center">
    <a href="https://x.com/Gramosoftpvtltd?s=20">
      <img src="https://camo.githubusercontent.com/8c6c7b3530573136a2550b2858664b1e2f38d3926e8b844a051f4ec182c99fac/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f466f6c6c6f772532306f6e253230582d3030303030303f7374796c653d666f722d7468652d6261646765266c6f676f3d78266c6f676f436f6c6f723d7768697465" alt="Follow on X" />
    </a>
    <a href="https://www.linkedin.com/showcase/gcrawlai/">
      <img src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/dev/feature/img/linked_in.svg" alt="Follow on LinkedIn" />
    </a>
  </p>
</div>

---

## ✨ Why GcrawlAI?

Most web crawlers dump raw HTML on your lap. GcrawlAI gives your LLM exactly what it needs — clean Markdown, structured metadata, and zero noise.

Here's what you can build with it:

🔍 RAG Pipelines — Feed your retrieval-augmented generation system with clean, structured web content instead of tag soup.

🤖 AI Search Tools — Index the web semantically. GcrawlAI extracts what matters, so your search understands context, not just keywords.

📄 Document Intelligence Systems — Turn web-based reports, filings, and articles into structured data your models can actually reason over.

💰 Price Monitoring Engines — Track competitor pricing across e-commerce platforms in real time, without a single broken XPath selector.

📊 Competitor Intelligence Dashboards — Continuously extract product updates, hiring signals, and announcements from competitor websites automatically.

🌐 Market Research Aggregators — Collect and synthesize data from hundreds of sources into clean, analysis-ready datasets.

🎯 Lead Generation Pipelines — Scrape company directories, job boards, and industry listings to build targeted, enriched prospect lists.

📰 News & Regulatory Trackers — Monitor policy changes, regulatory updates, and industry news without the noise of irrelevant content.

🛍️ Product Catalog Enrichers — Pull product descriptions, specs, and images from supplier sites and normalize them into your schema automatically.

No brittle CSS selectors. No HTML parsing headaches. No maintenance nightmares when a site redesigns overnight.

GcrawlAI handles the messy web so you don't have to.

- ⚡ **Instant or Deep** — Single page real-time extraction or full-site distributed crawling at scale
- 🧹 **LLM-Native Output** — Auto Markdown conversion, clean enough to feed directly into your vector store
- 🥷 **Stealth by Default** — Playwright stealth mode + automatic browser fallback to bypass bot detection
- 📊 **Real-Time Visibility** — Live WebSocket progress tracking and an interactive dashboard
- 🔐 **Secure Auth** — JWT + Email OTP, production-ready from day one
- 🌍 **Fully Open Source** — MIT licensed. Fork it, extend it, ship it

---

## 🚀 Features

| Feature                       | Description                                                                             |
| ----------------------------- | --------------------------------------------------------------------------------------- |
| **Single Page Crawl**         | Direct, real-time extraction from any individual URL — instant results                  |
| **Full Site Crawl**           | Distributed crawling of entire websites via Celery workers — handles thousands of pages |
| **LLM-Ready Markdown**        | Auto-converts web content into clean Markdown optimized for LLM consumption             |
| **HTML & Screenshot Capture** | Captures raw HTML and full-page screenshots for visual and structural analysis          |
| **SEO Metadata Extraction**   | Extracts title, description, keywords, and Open Graph tags automatically                |
| **Stealth & Anti-Bot**        | Playwright with stealth plugins; auto-fallback (Chromium → Firefox/Camoufox)            |
| **Real-Time Progress**        | Live crawl updates via WebSockets with an interactive dashboard                         |
| **Secure Auth**               | JWT-based auth, Email OTP signup/verification, and password reset flow                  |

## 🛠️ Technology Stack

- **Backend**: FastAPI, Python 3.9+
- **Frontend**: Angular
- **Database**: PostgreSQL
- **Task Queue**: Celery + Redis
- **Browser Automation**: Playwright
- **Authentication**: JWT, BCrypt

## 📋 Prerequisites

- **Python 3.9+**
- **PostgreSQL** (running on default port 5432)
- **Redis** (running on default port 6379)
- **Git**

### Linux System Dependencies

If you are running on Linux (Debian/Ubuntu), you will need to install the following system dependencies for the automated browsers to function correctly:

```bash
sudo apt update

sudo apt install -y \
libnss3 \
libatk1.0-0t64 \
libatk-bridge2.0-0t64 \
libcups2t64 \
libxcomposite1 \
libxdamage1 \
libxrandr2 \
libgbm1 \
libasound2t64 \
libpangocairo-1.0-0 \
libgtk-3-0t64
```

## ⚙️ Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/GramosoftAI/GcrawlAI.git
   cd GcrawlAI
   ```

2. **Create and activate virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Install Playwright browsers**
   ```bash
   playwright install
   ```

## 🔧 Configuration

1. **Database Config**: Update `config.yaml` with your PostgreSQL credentials.

   ```yaml
   postgres:
     host: "localhost"
     port: 5432
     database: "crawlerdb"
     user: "postgres"
     password: "your_password"
   ```

2. **Initialize Database Tables**:
   ```bash
   python -m api.db_setup
   # OR
   python api/db_setup.py
   ```

## �‍♂️ Running the Application

You need to run 4 separate processes. It's recommended to use separate terminal windows.

**1. Start Redis Server** (if not running as a service)

```bash
redis-server
```

> **⚠️ Windows Users:** Redis does not run natively on Windows. Use WSL (Windows Subsystem for Linux) or Docker instead.

**2. Start Celery Worker**

```bash
# Linux (User Recommended)
celery -A web_crawler.celery_config worker -l info

# Windows
celery -A web_crawler.celery_config.celery_app worker --loglevel=info --pool=solo
```

**3. Start Backend API**

```bash
# Windows / Development
uvicorn api.api:app --port 8000

# Linux / Production (User Recommended)
uvicorn api.api:app --host 0.0.0.0 --port 8000 --workers 4 --timeout-keep-alive 120
```

API Docs will be available at: http://localhost:8000/docs

**4. Start Frontend Dashboard**

<a href="https://github.com/GramosoftAI/GcrawlAI/blob/main/frontend/README.md">ReadMe for Angular Frontend</a>

## Project Structure

```
.
├── api/                    # FastAPI backend
│   ├── api.py              # Main API entry point
│   ├── auth_manager.py     # Authentication logic
│   └── db_setup.py         # Database initialization
├── web_crawler/            # Crawler logic
│   ├── web_crawler.py      # Core crawler orchestrator
│   ├── page_crawler.py     # Individual page processing
│   └── celery_config.py    # Celery configuration
├── config.yaml             # Application configuration
└── requirements.txt        # Python dependencies
```

## 🔐 API Endpoints

- `POST /crawler`: Start a new crawl job (single or all).
- `GET /crawler/status/{task_id}`: Check Celery task status.
- `GET /crawl/get/content`: Retrieve generated content.
- `POST /auth/signup/send-otp`: reliable email-based signup.
- `POST /auth/signup/verify-otp`: reliable email-based signup.
- `POST /auth/signin`: reliable email-based signin.
- `POST /auth/forgot-password`: reliable email-based forgot password.
- `POST /auth/reset-password`: reliable email-based reset password.

Full interactive API docs available at `http://localhost:8000/docs` when running locally.

---

## 🤝 Contributing

Contributions are welcome and appreciated! Here's how to get involved:

1. Fork the repository
2. Create a feature branch — `git checkout -b feature/YourFeature`
3. Commit your changes — `git commit -m 'Add YourFeature'`
4. Push to your branch — `git push origin feature/YourFeature`
5. Open a Pull Request

Please ensure your code follows the existing style and includes relevant tests. For large changes, open an issue first to discuss your proposal.

---

## 🙌 Credits & Inspiration

GcrawlAI was built by the team at **Gramosoft Private Limited**, inspired by the incredible open-source web scraping and AI ecosystem. We stand on the shoulders of giants:

| Project                                                          | What We Learned                                                                            |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| [🔥 Firecrawl](https://github.com/mendableai/firecrawl)          | LLM-ready markdown output, distributed crawling architecture, and benchmark-driven quality |
| [🕷️ ScrapeGraphAI](https://github.com/VinciGit00/Scrapegraph-ai) | Graph-based pipeline design and LLM-powered structured extraction                          |
| [🎭 Playwright](https://github.com/microsoft/playwright)         | Browser automation, stealth crawling, and anti-bot bypass strategies                       |
| [⚡ FastAPI](https://github.com/tiangolo/fastapi)                | High-performance async API design patterns                                                 |
| [🌿 Celery](https://github.com/celery/celery)                    | Distributed task queue architecture for large-scale crawling                               |
| [🔴 Redis](https://github.com/redis/redis)                       | In-memory message brokering for task queue management                                      |
| [🐘 PostgreSQL](https://www.postgresql.org)                      | Reliable relational data storage for crawl results and auth                                |

> **Disclaimer:** GcrawlAI is an independent open-source project built by Gramosoft Private Limited. All referenced projects are the intellectual property of their respective owners and contributors. GcrawlAI is not affiliated with, derived from, or endorsed by any of the above projects. We simply admire their work and credit them accordingly.

---

## 📄 License

GcrawlAI is released under the **MIT License**.

```
MIT License

Copyright (c) 2026 Gramosoft Private Limited

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

See the [LICENSE](./LICENSE) file for full details.

---

## 🙏 Acknowledgements

- Thank you to all contributors and the open-source community for your continued support
- GcrawlAI is intended for legitimate data extraction, AI development, and research purposes only
- Users are responsible for respecting websites' `robots.txt` directives, terms of service, and applicable privacy policies when crawling

---

<p align="center">
  Built with ❤️ by <a href="https://gramosoft.tech">Gramosoft Private Limited</a>
  <br><br>
  ⭐ If GcrawlAI saves you time, please <strong>star the repo</strong> — it helps others discover it!
  <br><br>
  <a href="#readme-top">↑ Back to Top ↑</a>
</p>
