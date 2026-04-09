import { Injectable } from '@angular/core';
import { Title, Meta, MetaDefinition } from '@angular/platform-browser';

@Injectable({
  providedIn: 'root'
})
export class SeoService {
  constructor(private title: Title, private meta: Meta) { }

  updateSeoTags(config: {
    title: string;
    description: string;
    keywords: string;
    author?: string;
    image?: string;
    url?: string;
    type?: string;
    twitterSite?: string;
    siteName?: string;
    robots?: string;
    canonical?: string;
  }) {
    this.title.setTitle(config.title);

    const tags: MetaDefinition[] = [
      { name: 'description', content: config.description },
      { name: 'keywords', content: config.keywords },
      { name: 'author', content: config.author || 'Gramosoft Private Limited' },
      { name: 'robots', content: config.robots || 'index, follow' },
      { property: 'og:title', content: config.title },
      { property: 'og:description', content: config.description },
      { property: 'og:url', content: config.url || 'https://gcrawl.gramopro.ai' },
      { property: 'og:type', content: config.type || 'website' },
      { property: 'og:site_name', content: config.siteName || 'GCrawl by Gramosoft' },
      { property: 'og:image', content: config.image || 'https://gcrawl.gramopro.ai/assets/image/Logo.svg' },
      { name: 'twitter:card', content: 'summary_large_image' },
      { name: 'twitter:title', content: config.title },
      { name: 'twitter:description', content: config.description },
      { name: 'twitter:site', content: config.twitterSite || '@GramosoftAI' },
      { name: 'twitter:image', content: config.image || 'https://gcrawl.gramopro.ai/assets/image/Logo.svg' }
    ];

    tags.forEach(tag => this.meta.updateTag(tag));

    if (config.canonical) {
      this.updateCanonicalLink(config.canonical);
    }
  }

  private updateCanonicalLink(url: string) {
    let link: HTMLLinkElement | null = document.querySelector('link[rel="canonical"]');
    if (!link) {
      link = document.createElement('link');
      link.setAttribute('rel', 'canonical');
      document.head.appendChild(link);
    }
    link.setAttribute('href', url);
  }
}