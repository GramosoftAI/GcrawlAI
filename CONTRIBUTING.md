# Contributing to GcrawlAI 🚀

Thank you for your interest in contributing to **GcrawlAI**! We welcome bug fixes, documentation improvements, new stealth heuristics, extractors, and feature proposals from the global developer community.

---

## 🛠️ Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please treat all contributors with respect and professionalism.

---

## 🚦 How Can You Contribute?

1. **Reporting Bugs**: Check existing issues first. If not reported, submit a detailed bug report using our [Bug Report Template](.github/ISSUE_TEMPLATE/bug_report.yml).
2. **Suggesting Enhancements**: Propose new features or extractor requests via our [Feature Request Template](.github/ISSUE_TEMPLATE/feature_request.yml).
3. **Submitting Pull Requests**: Solve open issues, improve documentation, or write test cases.
4. **Improving Documentation**: Fix typos, add Python/Node.js examples, or create tutorials.

---

## 💻 Development Setup

### 1. Fork & Clone
```bash
git clone https://github.com/YOUR_USERNAME/GcrawlAI.git
cd GcrawlAI
```

### 2. Python Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install
```

### 3. Branching Guidelines
Create a descriptive branch for your work:
```bash
git checkout -b feat/add-twitter-cookie-extractor
# or
git checkout -b fix/cloudflare-turnstile-timeout
```

---

## 📋 Pull Request (PR) Checklist

Before submitting your PR, ensure:
- [ ] Code follows PEP 8 standards for Python.
- [ ] New features include appropriate docstrings and unit tests.
- [ ] All tests pass locally (`pytest`).
- [ ] Commit messages follow the Conventional Commits specification:
  - `feat: add custom header support to /v1/scrape`
  - `fix: resolve memory leak in long-running crawler worker`
  - `docs: update quickstart guide with Node.js fetch example`
- [ ] No secrets, private API keys, or personal proxy credentials are included.

---

## 💬 Community & Questions

Need help or want to discuss an architecture proposal before building?
* Join our [GitHub Discussions](https://github.com/GramosoftAI/GcrawlAI/discussions)
* Reach out to the maintainers at: `support@gcrawlai.com`
