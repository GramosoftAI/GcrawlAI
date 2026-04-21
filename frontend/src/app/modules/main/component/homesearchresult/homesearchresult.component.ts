import { ChangeDetectorRef, Component, Inject, OnInit, PLATFORM_ID, ViewChild } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { Subject, takeUntil } from 'rxjs';
import { URLS } from 'src/app/configs/api.config';
import { ApiService } from 'src/app/services/api.service';
import { LocalStorageService } from 'src/app/services/localstorage-service';
import { marked } from 'marked';
import { QuoteSocketService } from 'src/app/services/websocket.service';
import { ToastrService } from 'ngx-toastr';
import { ActivatedRoute } from '@angular/router';
import { SeoService } from 'src/app/services/seo.service';
import { isPlatformBrowser } from '@angular/common';
import { CrawlHistoryComponent } from '../crawl-history/crawl-history.component';

@Component({
  selector: 'app-homesearchresult',
  templateUrl: './homesearchresult.component.html',
  styleUrls: ['./homesearchresult.component.scss']
})
export class HomesearchresultComponent implements OnInit {
  private destroy$ = new Subject<void>();
  activeTab: 'markdown' | 'json' = 'markdown';
  tabs = ['Python', 'Node.js', 'Curl'];
  activeTab1 = 'Python';
  markdownData: any;
  crawl_mode: any;
  crawlID: string | null = null;
  scrape: boolean = false;
  isLoading: boolean = false;
  loadingCounter: number = 0;
  isLogin: any;
  formValues: any;
  unSubscribe$ = new Subject();
  searchTooltipcontent = 'Search the web using a text query.'
  crawlform: FormGroup;
  socketMessages: string[] = [];
  pendingErrors: Set<string> = new Set();
  crawlCompleted: boolean = false;
  markdownBlocks: any[] = [];
  mode: any;
  formdata: any;
  selectedText = '';
  private visitedPaths = new Set<string>();
  private isBrowser: boolean;
  @ViewChild(CrawlHistoryComponent) crawlHistory!: CrawlHistoryComponent;
  linksTooltipcontent = 'Attempts to output all websites URLs in a few seconds.';
  scrapeTooltipcontent = 'Scrapes only the specified URL without scrapping subpages. Outputs the content from the page.'
  crawlTooltipcontent = 'Crawls a URL and all its accessible subpages, outputting the content from each page.'
  get formatLabel(): string {
    const labels: Record<string, string> = {
      enable_md: 'Markdown',
      enable_summary: 'Summary',
      enable_links: 'Links',
      enable_html: 'HTML',
      enable_ss: 'Screenshots',
      enable_json: 'JSON',
      enable_brand: 'Branding',
      enable_images: 'Images',
      enable_seo: 'SEO'
    };
    const selected = Object.keys(labels).filter(k => this.crawlform.get(k)?.value);
    if (selected.length === 0) return 'Format';
    if (selected.length === 1) return labels[selected[0]];
    return `${labels[selected[0]]} +${selected.length - 1}`;
  }

  constructor(private seoService: SeoService, private apiService: ApiService, private route: ActivatedRoute, private cd: ChangeDetectorRef, private toastr: ToastrService, private fb: FormBuilder,
    private localService: LocalStorageService, private socketService: QuoteSocketService, @Inject(PLATFORM_ID) private platformId: Object) {
    this.crawlform = this.fb.group({
      user_id: [null],
      url: ['', [Validators.required, Validators.pattern('https?://.+')]],
      crawl_mode: [''],
      enable_md: [true],
      enable_html: [false],
      enable_ss: [false],
      enable_seo: [false],
      enable_json: [false],
      enable_links: [false],
      enable_summary: [false],
      enable_brand: [false],
      enable_images: [false],
      button: ['scrape', [Validators.required]],
      limit: [10, [Validators.min(1), Validators.max(100)]],
    });

    this.isBrowser = isPlatformBrowser(this.platformId);
  }

  ngOnInit() {
    if (isPlatformBrowser(this.platformId)) {
      const id = this.localService.getCrawlID();
      this.crawlID = id ? id : null;
    }
    this.seoService.updateSeoTags({
      title: 'GCrawl — Free AI Web Crawler | Scrape Any Website into Markdown & LLM-Ready Data',
      description: 'GCrawl is a free, open-source AI web crawler by Gramosoft. Scrape any website into clean Markdown, HTML, Screenshots or SEO data in seconds.',
      keywords: 'web crawler, AI web scraper, website to markdown, LLM data extraction, open source web crawler',
      url: 'https://gcrawl.gramopro.ai',
      image: 'https://gcrawl.gramopro.ai/assets/image/Logo.svg'
    });

    this.route.queryParams.subscribe(params => {
      this.isLogin = params['isLogin'] === 'true';
    })
    this.formValues = this.localService.getformDetails();
    if (this.formValues) {
      this.crawlform.patchValue(this.formValues);
      // Strip stored https:// prefix so it doesn't double up with the static label
      const storedUrl = this.crawlform.get('url')?.value || '';
      this.crawlform.get('url')?.setValue(
        storedUrl.replace(/^(https?:\/\/)+/i, ''), { emitEvent: false }
      );
      this.formdata = this.formValues;
      this.updateSelectedText();
    }

    if (this.isLogin && this.formValues && !this.crawlID) {
      this.scrapStart();
    } else if (this.crawlID) {
      const storedPaths = this.localService.getStorage('discovery_paths');
      if (storedPaths && Array.isArray(storedPaths) && storedPaths.length > 0) {
        this.crawlCompleted = true;
        storedPaths.forEach((page: any) => {
          if (page.markdown) this.getContent(page.markdown, 'markdown', page.page);
          if (page.screenshot) this.getContent(page.screenshot, 'screenshot', page.page);
          if (page.engineHtml) this.getContent(page.engineHtml, 'html', page.page);
          if (page.links) this.getContent(page.links, 'links', page.page);
          if (page.summary) this.getContent(page.summary, 'summary', page.page);
          if (page.seo_md) this.getContent(page.seo_md, 'seo_md', page.page);
          if (page.seo_json) this.getContent(page.seo_json, 'seo_json', page.page);
          if (page.seo_xlsx) this.getContent(page.seo_xlsx, 'seo_xlsx', page.page);
          if (page.images) this.getContent(page.images, 'images', page.page);
        });
        this.scrape = true;
      } else {
        this.startSocket(this.crawlID);
        this.scrape = true;
      }
    }

  }

  setButton(value: string) {
    this.crawlform.patchValue({
      button: value
    });
    const urlControl = this.crawlform.get('url');
    const limitControl = this.crawlform.get('limit');
    if (value === 'search') {
      urlControl?.setValidators([Validators.required]);
      limitControl?.setValidators([Validators.required, Validators.min(1), Validators.max(100)]);
    } else {
      urlControl?.setValidators([Validators.required, Validators.pattern('https?://.+')]);
      limitControl?.setValidators([Validators.min(1), Validators.max(100)]);
    }
    urlControl?.updateValueAndValidity();
    limitControl?.updateValueAndValidity();
    if (value === 'links') {
      this.crawlform.patchValue({
        enable_md: false,
        enable_html: false,
        enable_ss: false,
        enable_seo: false,
        enable_json: false,
        enable_links: true,
        enable_summary: false,
        enable_brand: false,
        enable_images: false
      });
    } else if (value === 'search') {
      this.crawlform.patchValue({
        enable_links: false,
        enable_md: false,
        enable_html: false,
        enable_ss: false,
        enable_seo: false,
        enable_json: true,
        enable_summary: false,
        enable_brand: false,
        enable_images: false
      });
    } else {
      this.crawlform.patchValue({
        enable_links: false,
        enable_md: true,
        enable_json: false
      });
    }

    if (this.crawlHistory) {
      this.crawlHistory.getuserHistoryid();
    }
  }

  setOption(key: string, label: string) {
    const control = this.crawlform.get(key);
    if (!control) return;
    control.setValue(!control.value);
    this.updateSelectedText();
  }

  updateSelectedText() {

    const labels: any = {

      enable_md: 'Markdown',
      enable_summary: 'Summary',
      enable_links: 'Links',
      enable_html: 'HTML',
      enable_ss: 'Screenshots',
      enable_json: 'JSON',
      enable_brand: 'Branding',
      enable_images: 'Images',
      enable_seo: 'SEO'
    };

    const selected: string[] = [];

    Object.keys(labels).forEach(key => {

      if (this.crawlform.value[key]) {
        selected.push(labels[key]);
      }

    });

    this.selectedText = selected.join(', ');
  }

  getSelectedFormats() {
    const result: string[] = [];
    Object.keys(this.crawlform.value).forEach(key => {
      if (this.crawlform.value[key]) {
        result.push(key);
      }
    });
    return result;
  }

  Onsubmit() {
    debugger
    const isSearch = this.crawlform.get('button')?.value === 'search';
    if (!isSearch) {
      this.ensureHttps();
    }
    this.crawlform.markAllAsTouched();
    const urlControl = this.crawlform.get('url');
    const buttonControl = this.crawlform.get('button');

    // Bypass full form validation for search mode and just check the search query explicitly
    if (isSearch) {
      if (!urlControl?.value || !urlControl?.value.trim()) {
        this.toastr.error('Please enter a search query');
        return;
      }
      const limitControl = this.crawlform.get('limit');
      if (limitControl?.invalid) {
        this.toastr.error('Search limit must be between 1 and 100');
        return;
      }
      this.searchStart();
      return;
    }
    if (this.crawlform.invalid) {
      if (urlControl?.invalid) {
        this.toastr.error('Please enter website URL');
        return;
      }
      if (buttonControl?.invalid) {
        this.toastr.error('Please select crawl mode');
        return;
      }
      this.toastr.error('Please fill all required fields');
      return;
    }

    const formats = ['enable_md', 'enable_html', 'enable_ss', 'enable_seo', 'enable_json', 'enable_links', 'enable_summary', 'enable_brand', 'enable_images'];
    const anySelected = formats.some(key => this.crawlform.get(key)?.value);

    if (!anySelected) {
      this.toastr.error('Please select at least one format');
      return;
    }

    this.scrapStart();
    // Strip https:// back off so the static prefix label doesn't double up visually
    const urlCtrl = this.crawlform.get('url');
    if (urlCtrl) {
      urlCtrl.setValue(urlCtrl.value.replace(/^(https?:\/\/)+/i, ''), { emitEvent: false });
    }
  }

  /** Strip any protocol the user typed — the static prefix handles it */
  stripProtocol(event: Event) {
    if (this.crawlform.get('button')?.value === 'search') return;
    const input = event.target as HTMLInputElement;
    const cleaned = input.value.replace(/^(https?:\/\/)+/i, '');
    if (cleaned !== input.value) {
      this.crawlform.get('url')?.setValue(cleaned, { emitEvent: false });
    }
  }

  /** Ensure the URL stored in the form always starts with https:// */
  private ensureHttps() {
    const ctrl = this.crawlform.get('url');
    if (!ctrl) return;
    const raw = (ctrl.value || '').replace(/^(https?:\/\/)+/i, '');
    ctrl.setValue('https://' + raw, { emitEvent: false });
  }

searchStart() {
    this.scrape = false;
    this.isLoading = true;
    this.scrapReset();
    this.localService.clearcrawlID();
    this.mode = 'search';
    const normalizedLimit = this.getNormalizedSearchLimit();
    this.crawlform.patchValue({
      crawl_mode: 'search',
      user_id: this.localService.getUserDetails()?.user?.user_id || null,
      limit: normalizedLimit
    });
    const payload = { 
      query: this.crawlform.get('url')?.value?.trim(),
      limit: normalizedLimit
    };

    this.apiService.post(URLS.search, payload).pipe(takeUntil(this.destroy$)).subscribe({
      next: (res: any) => {
        this.formdata = this.crawlform.value;
        this.localService.setformDetails(this.formdata);
        this.scrape = true;
        
        let content = res.data ? res.data : res;
        
        // Return only the 'results' array if it exists.
        if (content && content.results) {
           content = content.results;
        }

        if (typeof content === 'object') {
           content = JSON.stringify(content, null, 2);
        }

        const newBlock: any = { seo_json: content, page: 0, title: payload.query };
        this.markdownBlocks = [newBlock];
        this.crawlCompleted = true;
        this.isLoading = false;
        this.cd.detectChanges();
      },
      error: (err: any) => {
        this.toastr.error(err?.error?.detail || 'Search failed');
        this.isLoading = false;
        this.cd.detectChanges();
      }
    });
  }

  private getNormalizedSearchLimit(): number {
    const rawValue = Number(this.crawlform.get('limit')?.value);
    if (!Number.isFinite(rawValue)) {
      return 10;
    }

    return Math.min(100, Math.max(1, Math.floor(rawValue)));
  }

  scrapStart() {
    debugger
    this.scrape = false; // Reset to trigger ngOnChanges later
    this.isLoading = true;
    this.scrapReset();
    this.localService.clearcrawlID();
    this.mode = this.crawlform.value.button;
    if (this.mode === 'scrape') {
      this.crawl_mode = 'single';
    } else if (this.mode === 'crawl') {
      this.crawl_mode = 'all';
    } else {
      this.crawl_mode = 'links';
      this.crawlform.patchValue({
        user_id: this.localService.getUserDetails()?.user?.user_id || null,
        enable_md: false,
        enable_html: false,
        enable_ss: false,
        enable_seo: false,
        enable_json: false,
        enable_links: true,
        enable_summary: false,
        enable_brand: false,
        enable_images: false
      });
    }
    this.crawlform.patchValue({
      crawl_mode: this.crawl_mode,
      user_id: this.localService.getUserDetails()?.user?.user_id || null,
    });
    this.apiService.post(URLS.config, this.crawlform.value).pipe(takeUntil(this.destroy$)).subscribe({
      next: (res: any) => {
        debugger
        this.formdata = this.crawlform.value;
        this.localService.setformDetails(this.formdata);
        if (res.status === 'completed' || res.status === 'queued') {
          this.scrape = true;
          if (res.crawl_id) {
            this.localService.setCrawlID(res.crawl_id);
          }
          if (this.crawl_mode === 'all' || this.crawl_mode === 'single' || this.crawl_mode === 'links') {
            this.startSocket(res.crawl_id);
          } else {
            this.getContent(res.markdown_path, 'markdown');
          }
        } else {
          debugger
          this.toastr.error(res.detail.detail)
          this.isLoading = false;
        }
      },
      error: () => {
        this.isLoading = false;
      }
    });
  }

  private isValidPath(path: any): boolean {
    if (!path) return false;
    if (typeof path !== 'string') return false;
    const p = path.trim().toLowerCase();
    return p !== '' && p !== 'none' && p !== 'null' && p !== 'undefined';
  }

  startSocket(crawlId: string) {
    debugger
    this.isLoading = true;
    this.crawlID = crawlId;
    this.socketService.connect(crawlId).pipe(takeUntil(this.destroy$)).subscribe({
      next: (data: any) => {
        console.log('Socket Raw Data:', JSON.stringify(data));

        if (data?.type === 'page_processed') {
          const pagePaths: any = { page: data.page };

          if (this.formdata?.enable_md) {
            if (this.isValidPath(data.markdown_file)) {
              pagePaths.markdown = data.markdown_file;
              this.getContent(data.markdown_file, 'markdown', data.page);
            } else if (this.formdata?.crawl_mode !== 'links') {
              this.pendingErrors.add('Generation failed for Markdown');
            }
          }
          if (this.formdata?.enable_ss) {
            if (this.isValidPath(data.screenshot)) {
              pagePaths.screenshot = data.screenshot;
              this.getContent(data.screenshot, 'screenshot', data.page);
            } else if (this.formdata?.crawl_mode !== 'links') {
              this.pendingErrors.add('Generation failed for Screenshot');
            }
          }
          if (this.formdata?.enable_html) {
            if (this.isValidPath(data.html_file)) {
              pagePaths.engineHtml = data.html_file;
              this.getContent(data.html_file, 'html', data.page);
            } else if (this.formdata?.crawl_mode !== 'links') {
              this.pendingErrors.add('Generation failed for HTML');
            }
          }
          if (this.formdata?.enable_links) {
            debugger
            if (this.isValidPath(data.links_file_path)) {
              pagePaths.links = data.links_file_path;
              this.getContent(data.links_file_path, 'links', data.page);
            } else if (this.formdata?.crawl_mode !== 'links') {
              this.pendingErrors.add('Generation failed for Links');
            }
          }
          if (this.formdata?.enable_summary) {
            if (this.isValidPath(data.summary_file)) {
              pagePaths.summary = data.summary_file;
              this.getContent(data.summary_file, 'summary', data.page);
            } else if (this.formdata?.crawl_mode !== 'links') {
              this.pendingErrors.add('Generation failed for Summary');
            }
          }
          if (this.formdata?.enable_seo) {
            if (this.isValidPath(data.seo_json)) {
              pagePaths.seo_json = data.seo_json;
              this.getContent(data.seo_json, 'seo_json', data.page);
            }
            if (this.isValidPath(data.seo_md)) {
              pagePaths.seo_md = data.seo_md;
              this.getContent(data.seo_md, 'seo_md', data.page);
            }
            if (this.isValidPath(data.seo_xlsx)) {
              pagePaths.seo_xlsx = data.seo_xlsx;
              this.getContent(data.seo_xlsx, 'seo_xlsx', data.page);
            }

            if (!this.isValidPath(data.seo_json) && !this.isValidPath(data.seo_md) && !this.isValidPath(data.seo_xlsx)) {
              if (this.formdata?.crawl_mode !== 'links') this.pendingErrors.add('Generation failed for SEO Data');
            }
          }
          if (this.formdata?.enable_images) {
            if (this.isValidPath(data.images)) {
              pagePaths.images = data.images;
              this.getContent(data.images, 'images', data.page);
            } else if (this.formdata?.crawl_mode !== 'links') {
              this.pendingErrors.add('Generation failed for Images');
            }
          }
          this.savePagePaths(pagePaths);

        } else if (data?.type === 'crawl_completed') {
          const summary = data?.summary || {};
          const mdPath = summary.markdown_file ?? summary.markdown_path;
          const linksPath = summary.links_file_path || data?.links_file_path;
          const jsonSummaryPath = summary.summary_file || data?.summary_file_path;

          if (this.formdata?.enable_links) {
            if (this.isValidPath(linksPath)) {
              if (!this.visitedPaths.has(linksPath)) this.getContent(linksPath, 'links');
            } else {
              this.pendingErrors.add('Final Links file generation failed');
            }
          }

          if (this.formdata?.enable_md) {
            if (this.isValidPath(mdPath)) {
              if (mdPath.toLowerCase().endsWith('.md') && !this.visitedPaths.has(mdPath)) {
                this.getContent(mdPath, 'markdown');
              }
            } else {
              this.pendingErrors.add('Final Markdown file generation failed');
            }
          }

          if (this.formdata?.enable_summary) {
            if (this.isValidPath(jsonSummaryPath)) {
              if (!this.visitedPaths.has(jsonSummaryPath)) this.getContent(jsonSummaryPath, 'summary');
            } else {
              this.pendingErrors.add('Final Summary file generation failed');
            }
          }

          // Show all accumulated errors uniquely
          if (this.pendingErrors.size > 0) {
            this.pendingErrors.forEach(err => this.toastr.error(err));
            this.pendingErrors.clear();
          }

          this.crawlCompleted = true;
          if (this.loadingCounter === 0) {
            this.isLoading = false;
            this.cd.detectChanges();
          }
        }
      },
      error: (err) => {
        console.error('Socket Error:', err);
        this.toastr.error('Socket Error:', err);
        this.isLoading = false;
        this.cd.detectChanges();
      },
      complete: () => {
        this.isLoading = false;
        this.cd.detectChanges();
      }
    });
  }

  scrapReset() {
    this.markdownBlocks = [];
    this.visitedPaths.clear();
    this.pendingErrors.clear();
    this.crawlCompleted = false;
    this.loadingCounter = 0;
    this.localService.removeStorage('discovery_paths');
  }

  private savePagePaths(newPaths: any) {
    const existing = this.localService.getStorage('discovery_paths') || [];
    let page = existing.find((p: any) => p.page === newPaths.page);
    if (!page) {
      page = { page: newPaths.page };
      existing.push(page);
    }
    Object.assign(page, newPaths);
    existing.sort((a: any, b: any) => a.page - b.page);
    this.localService.setStorage('discovery_paths', existing);
  }

  processBatch() {
    const combined = this.socketMessages.join('\n\n');
    this.markdownBlocks.push(combined);
  }

  getContent(path: any, type: 'markdown' | 'screenshot' | 'html' | 'links' | 'summary' | 'seo_json' | 'seo_md' | 'seo_xlsx' | 'images', pageIndex?: number) {
    debugger
    if (!path || this.visitedPaths.has(path)) return;
    this.visitedPaths.add(path);

    if (this.formdata?.crawl_mode === 'single' && type === 'markdown') {
      this.localService.setCrawlID(path);
    }
    const params = { file_path: path };
    this.loadingCounter++;
    this.isLoading = true;
    this.apiService.get(URLS.markdown_Details, params, true).pipe(takeUntil(this.destroy$)).subscribe({
      next: (res: any) => {
        // Automatically unwrap 'data' payload from typical API responses
        const payload = res.data ? res.data : res;

        let content = payload.markdown || payload.image || payload.screenshot || payload.content || payload.json || payload.xlsx || payload.seo_md || payload.markdown_content || payload.seo_xlsx || payload;

        if (typeof content === 'object' && content !== null) {
          if (type === 'seo_json') content = content.json || content.seo_json || content.content || content;
          if (type === 'seo_xlsx') content = content.xlsx || content.seo_xlsx || content.content || content;
          if (type === 'seo_md') content = content.markdown || content.seo_md || content.content || content;
          if (type === 'markdown') content = content.markdown || content.content || content;
          if (type === 'screenshot') content = content.screenshot || content.image || content.content || content;
          if (type === 'html') content = content.html || content.engineHtml || content.content || content;
          if (type === 'images') content = content.json || content.content || content;
        }

        // Failsafe serialization if it's still somehow an object, to prevent silent JS errors crashing marked parses.
        if (typeof content === 'object' && content !== null && type !== 'seo_json' && type !== 'seo_xlsx') {
          try {
            content = content.content || content.markdown || JSON.stringify(content, null, 2);
          } catch (e) { }
        }

        if (type === 'seo_json' && typeof content === 'object') {
          content = JSON.stringify(content, null, 2);
        }

        if (type === 'screenshot' && typeof content === 'string' && !content.startsWith('data:')) {
          content = `data:image/png;base64,${content}`;
        }
        const keyMap: any = {
          'markdown': 'raw', // Or 'markdown'
          'html': 'engineHtml',
          'screenshot': 'screenshot',
          'links': 'links',
          'summary': 'summary',
          'seo_json': 'seo_json',
          'seo_md': 'seo_md',
          'seo_xlsx': 'seo_xlsx',
          'images': 'images'
        };
        const key = keyMap[type] || type;

        if (pageIndex !== undefined) {
          let blockIndex = this.markdownBlocks.findIndex(b => b.page === pageIndex);
          if (blockIndex === -1) {
            const newBlock: any = { page: pageIndex, [key]: content };
            if (res.title) newBlock.title = res.title;
            this.markdownBlocks = [...this.markdownBlocks, newBlock].sort((a, b) => a.page - b.page);
          } else {
            const updatedBlock = { ...this.markdownBlocks[blockIndex], [key]: content };
            if (res.title && !updatedBlock.title) updatedBlock.title = res.title;
            const newBlocks = [...this.markdownBlocks];
            newBlocks[blockIndex] = updatedBlock;
            this.markdownBlocks = newBlocks;
          }
        } else {
          const newBlock: any = { [key]: content, page: 0 };
          if (res.title) newBlock.title = res.title;
          this.markdownBlocks = [...this.markdownBlocks, newBlock];
        }

        this.loadingCounter--;
        this.isLoading = this.crawlCompleted ? this.loadingCounter > 0 : true;

        this.cd.detectChanges();
      },
      error: () => {
        this.loadingCounter--;
        this.isLoading = this.crawlCompleted ? this.loadingCounter > 0 : true;

        this.toastr.error('Something went wrong')
        this.cd.detectChanges();
      }
    });
  }

  downloadMarkdown(content: string, index: number) {
    if (!this.isBrowser) return;
    const blob = new Blob([content], {
      type: 'text/markdown;charset=utf-8'
    });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `report_${index + 1}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  }



  onHistoricalReportClicked(historyResponse: any) {
    if (!historyResponse || !historyResponse.pages || historyResponse.pages.length === 0) {
      this.toastr.info("No content available for this report.");
      return;
    }

    this.scrapReset();
    this.isLoading = true;
    this.scrape = true;
    this.crawlCompleted = true; // Historical is treated as already finished

    // We update the local formdata to infer types of buttons, but we don't know the precise mode
    // We can infer by checking if it's more than 1 page (crawl vs scrape)
    const isCrawl = historyResponse.pages.length > 1;
    this.formdata = {
      enable_md: historyResponse.pages.some((p: any) => p.markdown_file),
      enable_html: historyResponse.pages.some((p: any) => p.html_file),
      enable_seo: historyResponse.pages.some((p: any) => p.seo_json || p.seo_md || p.seo_xlsx),
      enable_links: historyResponse.pages.some((p: any) => p.links_file_path || p.links),
      enable_ss: historyResponse.pages.some((p: any) => p.screenshot),
      enable_images: historyResponse.pages.some((p: any) => p.images),
      enable_summary: historyResponse.pages.some((p: any) => p.summary_file),
      button: isCrawl ? 'crawl' : 'scrape'
    };

    historyResponse.pages.forEach((page: any, index: number) => {
      // Notice we pass mapping to getContent (path, type, index)
      // Manually add the title/url to a blank initial object to help `getContent` attach it if `res.title` isn't available
      const tempBlock = { page: index, title: page.title, url: page.url };
      if (!this.markdownBlocks[index]) {
        this.markdownBlocks[index] = tempBlock;
      } else {
        this.markdownBlocks[index].title = page.title;
        this.markdownBlocks[index].url = page.url;
      }

      if (page.markdown_file) this.getContent(page.markdown_file, 'markdown', index);
      if (page.html_file) this.getContent(page.html_file, 'html', index);
      if (page.screenshot) this.getContent(page.screenshot, 'screenshot', index);
      // Backend sometimes sends `links` and sometimes `links_file_path`
      const linksPath = page.links_file_path || page.links;
      if (linksPath) this.getContent(linksPath, 'links', index);
      if (page.summary_file) this.getContent(page.summary_file, 'summary', index);
      if (page.seo_json) this.getContent(page.seo_json, 'seo_json', index);
      if (page.seo_md) this.getContent(page.seo_md, 'seo_md', index);
      if (page.seo_xlsx) this.getContent(page.seo_xlsx, 'seo_xlsx', index);
      if (page.images) this.getContent(page.images, 'images', index);
    });

    if (this.loadingCounter === 0) {
      this.isLoading = false;
      this.cd.detectChanges();
    }

    // Scroll to the top of the page when the report starts loading so the user focuses on the tabs
    if (this.isBrowser) {
      setTimeout(() => {
        window.scrollTo({ top: 300, behavior: 'smooth' });
      }, 300);
    }
  }

  ngOnDestroy() {
    this.destroy$.next();
    this.destroy$.complete();

  }

}
