<h3 align="center">
  <a name="readme-top"></a>
  <img
    src="https://raw.githubusercontent.com/GramosoftAI/GcrawlAI/refs/heads/dev/feature/img/Crawl%20Logo.svg"
    height="200"
  >
</h3>

<div align="center">
  <a href="#">
    <img src="https://img.shields.io/github/license/firecrawl/firecrawl" alt="License">
  </a>
  <a href="https://pepy.tech/project/firecrawl-py">
    <img src="https://static.pepy.tech/badge/firecrawl-py" alt="Downloads">
  </a>
  <a href="https://GitHub.com/firecrawl/firecrawl/graphs/contributors">
    <img src="https://img.shields.io/github/contributors/firecrawl/firecrawl.svg" alt="GitHub Contributors">
  </a>
  <a href="https://firecrawl.dev">
    <img src="https://img.shields.io/badge/Visit-firecrawl.dev-orange" alt="Visit firecrawl.dev">
  </a>
</div>

<div>
  <p align="center">
    <a href="https://twitter.com/firecrawl_dev">
      <img src="https://img.shields.io/badge/Follow%20on%20X-000000?style=for-the-badge&logo=x&logoColor=white" alt="Follow on X" />
    </a>
    <a href="https://www.linkedin.com/company/104100957">
      <img src="https://img.shields.io/badge/Follow%20on%20LinkedIn-0077B5?style=for-the-badge&logo=linkedin&logoColor=white" alt="Follow on LinkedIn" />
    </a>
    <a href="https://discord.com/invite/gSmWdAkdwd">
      <img src="https://img.shields.io/badge/Join%20our%20Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Join our Discord" />
    </a>
  </p>
</div>

---

# Web Crawler API & Dashboard

A comprehensive web crawling solution featuring a FastAPI backend, Streamlit dashboard, and distributed task processing with Celery and Redis.

## 🚀 Features

- **Dual Mode Crawling**:
  - **Single Page**: Direct, real-time crawling of individual pages.
  - **Full Site**: Distributed crawling of entire websites using Celery workers.
- **Advanced Extraction**:
  - Markdown conversion for LLM consumption.
  - HTML & Screenshot capture.
  - SEO metadata extraction (Title, Description, Keywords).
- **Stealth & Anti-Blocking**:
  - Uses Playwright with stealth plugins to bypass bot detection.
  - Automatic fallback strategies (Chromium -> Firefox/Camoufox).
- **Real-time Updates**:
  - Live progress tracking via WebSockets.
  - Interactive Streamlit dashboard.
- **Authentication**:
  - JWT-based authentication.
  - Email OTP for signup/verification.
  - Password reset flow.

## 🛠️ Technology Stack

- **Backend**: FastAPI, Python 3.9+
- **Frontend**: Streamlit
- **Database**: PostgreSQL
- **Task Queue**: Celery + Redis
- **Browser Automation**: Playwright
- **Authentication**: JWT, BCrypt

## 📋 Prerequisites

- **Python 3.9+**
- **PostgreSQL** (running on default port 5432)
- **Redis** (running on default port 6379)
- **Git**

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
Note: Redis server will not run on windows, so use WSL for running redis server. or use docker.

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
uvicorn api.api:app --reload --port 8000

# Linux / Production (User Recommended)
uvicorn api.api:app --host 0.0.0.0 --port 8000 --workers 4 --timeout-keep-alive 120
```
API Docs will be available at: http://localhost:8000/docs

**4. Start Frontend Dashboard**
```bash
cd web_crawler
streamlit run streamlit_app.py
```
Dashboard will be available at: http://localhost:8501

## � Project Structure

```
.
├── api/                    # FastAPI backend
│   ├── api.py              # Main API entry point
│   ├── auth_manager.py     # Authentication logic
│   └── db_setup.py         # Database initialization
├── web_crawler/            # Crawler logic
│   ├── web_crawler.py      # Core crawler orchestrator
│   ├── page_crawler.py     # Individual page processing
│   ├── streamlit_app.py    # Frontend dashboard
│   └── celery_config.py    # Celery configuration
├── config.yaml             # Application configuration
└── requirements.txt        # Python dependencies
```

## 🔐 API Endpoints

- `POST /crawler`: Start a new crawl job (single or all).
- `GET /crawler/status/{task_id}`: Check Celery task status.
- `GET /crawl/markdown`: Retrieve generated markdown.
- `POST /auth/signup/send-otp`: reliable email-based signup.
- `POST /auth/signup/verify-otp`: reliable email-based signup.
- `POST /auth/signin`: reliable email-based signin.
- `POST /auth/forgot-password`: reliable email-based forgot password.
- `POST /auth/reset-password`: reliable email-based reset password.

