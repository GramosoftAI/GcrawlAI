import { Component, OnInit } from '@angular/core';
import { ThemeService } from './services/theme.service';
import { SeoService } from './services/seo.service';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss']
})
export class AppComponent implements OnInit {
  title = 'gramocrawl';

  constructor(private themeService: ThemeService, private seoService: SeoService) { }

  ngOnInit(): void {
    this.seoService.updateSeoTags({
      title: 'GCrawl — Free AI Web Crawler | Scrape Any Website into Markdown & LLM-Ready Data',
      description: 'GCrawl is a free, open-source AI web crawler by Gramosoft. Scrape any website into clean Markdown, HTML, Screenshots or SEO data in seconds.',
      keywords: 'web crawler, AI web scraper, website to markdown, LLM data extraction, open source web crawler',
      url: 'https://gcrawl.gramopro.ai',
      image: 'https://gcrawl.gramopro.ai/assets/image/Logo.svg'
    });
  }
}
