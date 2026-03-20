import { ChangeDetectorRef, Component, Inject, OnInit, PLATFORM_ID } from '@angular/core';
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
  crawlform: FormGroup;
  socketMessages: string[] = [];
  markdownBlocks: any[] = [];
  mode: any;
  formdata: any;
  selectedText = '';
  private visitedPaths = new Set<string>();
  private isBrowser: boolean;
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
      enable_image: 'Images',
      enable_seo: 'SEO'
    };
    const selected = Object.keys(labels).filter(k => this.crawlform.get(k)?.value);
    if (selected.length === 0) return 'Format';
    if (selected.length === 1) return labels[selected[0]];
    return `${labels[selected[0]]} +${selected.length - 1}`;
  }

  constructor(private seoservice: SeoService, private apiService: ApiService, private route: ActivatedRoute, private cd: ChangeDetectorRef, private toastr: ToastrService, private fb: FormBuilder,
    private localService: LocalStorageService, private socketService: QuoteSocketService, @Inject(PLATFORM_ID) private platformId: Object) {
    this.crawlform = this.fb.group({
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
      enable_image: [false],
      button: ['scrape', [Validators.required]]
    });

    this.isBrowser = isPlatformBrowser(this.platformId);
  }

  ngOnInit() {
    if (isPlatformBrowser(this.platformId)) {
      const id = this.localService.getCrawlID();
      this.crawlID = id ? id : null;
    }
    this.seoservice.updateSeoTags({
      title: 'Crawler Dashboard | Gramocrawl',
      description: 'Manage your distributed crawl tasks, monitor Celery workers, and view real-time scraping progress.',
      keywords: 'scraping dashboard, celery monitor, real-time crawler',
      image: 'assets/dashboard-preview.jpg'
    });

    this.route.queryParams.subscribe(params => {
      this.isLogin = params['isLogin'] === 'true';
      console.log('isLogin', this.isLogin)
    })
    this.formValues = this.localService.getformDetails();
    if (this.formValues) {
      this.crawlform.patchValue(this.formValues);
      this.formdata = this.formValues;
      this.updateSelectedText();
    }

    if (this.isLogin && this.formValues && !this.crawlID) {
      this.scrapStart();
    } else if (this.crawlID) {
      const storedPaths = this.localService.getStorage('discovery_paths');
      if (storedPaths && Array.isArray(storedPaths) && storedPaths.length > 0) {
        storedPaths.forEach((page: any) => {
          if (page.markdown) this.getContent(page.markdown, 'markdown', page.page);
          if (page.screenshot) this.getContent(page.screenshot, 'screenshot', page.page);
          if (page.engineHtml) this.getContent(page.engineHtml, 'html', page.page);
          if (page.links) this.getContent(page.links, 'links', page.page);
          if (page.summary) this.getContent(page.summary, 'summary', page.page);
          if (page.seo_md) this.getContent(page.seo_md, 'seo_md', page.page);
          if (page.seo_json) this.getContent(page.seo_json, 'seo_json', page.page);
          if (page.seo_xlsx) this.getContent(page.seo_xlsx, 'seo_xlsx', page.page);
        });
        this.scrape = true;
      } else {
        // ID exists but no results recovered -> Scan might be ongoing or results lost -> Reconnect socket
        this.startSocket(this.crawlID);
        this.scrape = true;
      }
    }

  }

  setButton(value: string) {
    this.crawlform.patchValue({
      button: value
    });

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
        enable_image: false
      });
    } else {
      // If switching from links back to scrape or crawl, unset links and set md
      this.crawlform.patchValue({
        enable_links: false,
        enable_md: true
      });
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
      enable_image: 'Images',
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
    console.log('Selected:', result);
    return result;
  }

  Onsubmit() {
    this.crawlform.markAllAsTouched();
    if (this.crawlform.invalid) {
      const { url, button } = this.crawlform.controls;
      if (url?.invalid) {
        this.toastr.error('Please enter website URL');
        return;
      }
      if (button?.invalid) {
        this.toastr.error('Please select crawl mode');
        return;
      }
      this.toastr.error('Please fill all required fields');
      return;
    }

    // Check if at least one output format is selected
    const formats = ['enable_md', 'enable_html', 'enable_ss', 'enable_seo', 'enable_json', 'enable_links', 'enable_summary', 'enable_brand', 'enable_image'];
    const anySelected = formats.some(key => this.crawlform.get(key)?.value);

    if (!anySelected) {
      this.toastr.error('Please select at least one format');
      return;
    }

    this.scrapStart();
  }



  scrapStart() {
    debugger
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
        enable_md: false,
        enable_html: false,
        enable_ss: false,
        enable_seo: false,
        enable_json: false,
        enable_links: true,
        enable_summary: false,
        enable_brand: false,
        enable_image: false
      });
    }
    this.crawlform.patchValue({
      crawl_mode: this.crawl_mode
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

  startSocket(crawlId: string) {
    debugger
    this.isLoading = true;
    this.crawlID = crawlId;
    this.socketService.connect(crawlId).pipe(takeUntil(this.destroy$)).subscribe({
      next: (data: any) => {
        console.log('Socket Raw Data:', JSON.stringify(data));

        if (data?.type === 'page_processed') {
          const pagePaths: any = { page: data.page };

          if (data.markdown_file && this.formdata?.enable_md) {
            pagePaths.markdown = data.markdown_file;
            this.getContent(data.markdown_file, 'markdown', data.page);
          }
          if (data.screenshot && this.formdata?.enable_ss) {
            pagePaths.screenshot = data.screenshot;
            this.getContent(data.screenshot, 'screenshot', data.page);
          }
          if (data.html_file && this.formdata?.enable_html) {
            pagePaths.engineHtml = data.html_file;
            this.getContent(data.html_file, 'html', data.page);
          }
          if (data.links_file_path && this.formdata?.enable_links) {
            pagePaths.links = data.links_file_path;
            this.getContent(data.links_file_path, 'links', data.page);
          }
          if (data.summary_file && this.formdata?.enable_summary) {
            pagePaths.summary = data.summary_file;
            this.getContent(data.summary_file, 'summary', data.page);
          }
          if (data.seo_json && this.formdata?.enable_seo) {
            pagePaths.seo_json = data.seo_json;
            this.getContent(data.seo_json, 'seo_json', data.page);
          }
          if (data.seo_md && this.formdata?.enable_seo) {
            pagePaths.seo_md = data.seo_md;
            this.getContent(data.seo_md, 'seo_md', data.page);
          }
          if (data.seo_xlsx && this.formdata?.enable_seo) {
            pagePaths.seo_xlsx = data.seo_xlsx;
            this.getContent(data.seo_xlsx, 'seo_xlsx', data.page);
          }
          this.savePagePaths(pagePaths);

        } else if (data?.type === 'crawl_completed') {
          const mdPath = data?.summary?.markdown_file ?? data?.summary?.markdown_path;
          const linksPath = data?.summary?.links_file_path || data?.links_file_path;
          const jsonSummaryPath = data?.summary?.summary_file || data?.summary_file_path;

          if (linksPath && this.formdata?.enable_links && !this.visitedPaths.has(linksPath)) {
            this.getContent(linksPath, 'links');
          }
          if (mdPath && this.formdata?.enable_md && mdPath.toLowerCase().endsWith('.md') && !this.visitedPaths.has(mdPath)) {
            this.getContent(mdPath, 'markdown');
          }
          if (jsonSummaryPath && this.formdata?.enable_summary && !this.visitedPaths.has(jsonSummaryPath)) {
            this.getContent(jsonSummaryPath, 'summary');
          }
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

  getUserhistory() {
    debugger
    const user_id = 4;
    const urlWithId = `${URLS.user_history}/${user_id}`;
    this.apiService.get(urlWithId, null, true).pipe(takeUntil(this.destroy$)).subscribe({
      next: (res: any) => {
        console.log('History Data:', res);
      }
    });
  }

  getContent(path: any, type: 'markdown' | 'screenshot' | 'html' | 'links' | 'summary' | 'seo_json' | 'seo_md' | 'seo_xlsx', pageIndex?: number) {
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
        let content = res.markdown || res.image || res.screenshot || res.content || res.json || res.xlsx || res.seo_md || res.markdown_content || res;
        if (typeof content === 'object' && content !== null) {
          if (type === 'seo_json' && content.json) content = content.json;
          if (type === 'seo_xlsx' && content.xlsx) content = content.xlsx;
          if (type === 'seo_md' && content.markdown) content = content.markdown;
        }
        if (type === 'seo_json' && typeof content === 'object') {
          content = JSON.stringify(content, null, 2);
        }

        if (type === 'screenshot' && typeof content === 'string' && !content.startsWith('data:')) {
          content = `data:image/png;base64,${content}`;
        }
        if (pageIndex !== undefined) {
          let blockIndex = this.markdownBlocks.findIndex(b => b.page === pageIndex);
          if (blockIndex === -1) {
            const newBlock = { page: pageIndex, [type === 'html' ? 'engineHtml' : type]: content };
            this.markdownBlocks = [...this.markdownBlocks, newBlock].sort((a, b) => a.page - b.page);
          } else {
            const updatedBlock = { ...this.markdownBlocks[blockIndex], [type === 'html' ? 'engineHtml' : type]: content };
            const newBlocks = [...this.markdownBlocks];
            newBlocks[blockIndex] = updatedBlock;
            this.markdownBlocks = newBlocks;
          }
        } else {
          const key = (type === 'html' ? 'engineHtml' : type);
          this.markdownBlocks = [...this.markdownBlocks, { [key]: content, page: 0 }];
        }

        this.loadingCounter--;
        this.isLoading = this.loadingCounter > 0;
        this.cd.detectChanges();
      },
      error: () => {
        this.loadingCounter--;
        this.isLoading = this.loadingCounter > 0;
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



  ngOnDestroy() {
    this.destroy$.next();
    this.destroy$.complete();

  }

}
