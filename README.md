# GcrawlAI

### Open-Source LLM-Ready Web Crawler & Data Extraction Platform

Empower your AI applications with clean, structured data from any website.

---

## 🚀 What is GcrawlAI?

GcrawlAI is a comprehensive API service that transforms any URL into clean, LLM-ready data formats. Simply provide a URL, and GcrawlAI intelligently crawls all accessible pages, delivering structured content without requiring sitemaps or complex configurations.

---

## ✨ Core Capabilities

### Data Extraction Methods

- **Scrape**: Extract content from individual URLs and convert to LLM-optimized formats including markdown, structured data via AI extraction, screenshots, and HTML.

- **Crawl**: Automatically discover and scrape all URLs within a website, returning comprehensive content in machine-readable formats.

- **Map**: Rapidly generate complete URL lists for entire websites with exceptional speed.

- **Search**: Perform web searches and retrieve full content from search results.

- **Extract**: Leverage AI to extract structured data from single pages, multiple pages, or complete websites with precision.

### Advanced Features

- **LLM-Optimized Output**: Generate clean markdown, structured data, screenshots, HTML, extracted links, and comprehensive metadata.

- **Enterprise-Grade Infrastructure**: Built-in proxy management, anti-bot circumvention, dynamic JavaScript rendering, intelligent output parsing, and orchestration.

- **Extensive Customization**: Configure tag exclusions, authenticate behind login walls with custom headers, control crawl depth, and fine-tune extraction parameters.

- **Multi-Format Support**: Process PDFs, DOCX documents, and images seamlessly.

- **Reliability Architecture**: Engineered to extract data successfully regardless of website complexity or protection mechanisms.

- **Interactive Actions**: Execute clicks, scrolls, form inputs, wait conditions, and other browser interactions before data extraction.

- **High-Volume Processing**: Leverage asynchronous batch endpoints to scrape thousands of URLs concurrently.

- **Change Detection**: Monitor websites for content modifications and track changes over time.

---

## 💡 Use Cases

Perfect for:
- Building AI agents
- Training datasets
- Market research automation
- Competitive intelligence
- Content aggregation
- Any application requiring clean, structured web data at scale

---

## 🛠️ Getting Started

### Installation
```bash
pip install gcrawlai
```

### Basic Usage
```python
from gcrawlai import WebCrawler

# Initialize crawler
crawler = WebCrawler()

# Scrape a single page
result = crawler.scrape("https://example.com")
print(result.markdown)

# Crawl entire website
results = crawler.crawl("https://example.com", max_depth=3)
for page in results:
    print(page.url, page.markdown)
```

### API Integration
```python
import requests

# Scrape endpoint
response = requests.post('https://api.gcrawlai.com/scrape', 
    json={'url': 'https://example.com'})

# Extract structured data
response = requests.post('https://api.gcrawlai.com/extract',
    json={
        'url': 'https://example.com',
        'schema': {'title': 'string', 'price': 'number'}
    })
```

---

## 🎯 Key Features in Detail

### AI-Powered Extraction
Extract structured data using LLM-based parsing with custom schemas, automatic field detection, and intelligent data normalization.

### Dynamic Content Handling
Execute JavaScript, wait for dynamic elements, handle infinite scroll, and interact with single-page applications.

### Authentication Support
Pass custom headers, cookies, and authentication tokens to crawl content behind login walls and protected areas.

### Batch Processing
Process thousands of URLs concurrently with optimized resource management and automatic retry mechanisms.

### Change Monitoring
Track content changes, receive notifications, and maintain historical versions for compliance and analysis.

---

## 📚 Documentation

For comprehensive documentation, examples, and API references, visit:

- **Documentation**: [https://docs.gcrawlai.com](https://docs.gcrawlai.com)
- **GitHub Repository**: [https://github.com/gramosoft/gcrawlai](https://github.com/gramosoft/gcrawlai)
- **API Reference**: [https://api.gcrawlai.com/docs](https://api.gcrawlai.com/docs)

---

## 📄 License

Open-source under MIT License

---

## 🤝 Support

- **GitHub Issues**: Report bugs and request features
- **Community Discord**: Get help and share use cases
- **Enterprise Support**: Contact for dedicated support and custom solutions

---

## 🏢 About

**Built by Gramosoft Private Limited**

A Chennai-based IT services company specializing in AI/ML solutions, web and mobile development, and cloud consulting.

---

**Built for developers who need reliable, scalable web data extraction for AI and automation workflows.**

---

## 🌟 Star Us

If you find GcrawlAI useful, please consider giving us a star on GitHub!

[![GitHub stars](https://img.shields.io/github/stars/gramosoft/gcrawlai.svg?style=social&label=Star)](https://github.com/GramosoftAI/gcrawlai)
