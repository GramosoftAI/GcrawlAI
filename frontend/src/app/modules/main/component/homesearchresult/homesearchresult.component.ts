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
import { LoaderService } from 'src/app/services/loader-service';

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
  isLogin: any;
  formValues: any;
  unSubscribe$ = new Subject();
  crawlform: FormGroup;
  socketMessages: string[] = [];
  markdownBlocks: string[] = [];
  formdata: any;
  private isBrowser: boolean;

  constructor(private seoservice: SeoService, private apiService: ApiService, private route: ActivatedRoute, private cd: ChangeDetectorRef, private toastr: ToastrService, private fb: FormBuilder,
    private localService: LocalStorageService, private socketService: QuoteSocketService, @Inject(PLATFORM_ID) private platformId: Object, private loaderservice: LoaderService) {
    this.crawlform = this.fb.group({
      url: ['', [Validators.required, Validators.pattern('https?://.+')]],
      crawl_mode: [''],
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
      const isLogin = [params['isLogin'] === true];
      this.isLogin = isLogin;
      console.log('isLogin', isLogin)
    })
    this.formValues = this.localService.getformDetails();
    if (!this.scrape && this.crawlID && this.isLogin && this.formValues?.crawl_mode === 'single') {
      this.getMarkdown(this.localService.getCrawlID())
    } else if (this.isLogin && this.formValues?.crawl_mode === 'all') {
      this.crawlform.patchValue(this.formValues)
      this.scrapStart()
    }
  }

  setButton(value: string) {
    this.crawlform.patchValue({
      button: value
    });
  }

Onsubmit(type: 'before' | 'after') {
debugger
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

  // Optional: track which form submitted
  console.log('Submitted from:', type);

  this.scrapStart();
}

  scrapStart() {
    this.isLoading = true;
    this.localService.clearcrawlID();
    const mode = this.crawlform.value.button === 'scrape' ? 'single' : 'all';
    this.crawl_mode = mode;
    this.crawlform.patchValue({
      crawl_mode: mode
    });
    this.apiService.post(URLS.config, this.crawlform.value).pipe(takeUntil(this.destroy$)).subscribe({
      next: (res: any) => {
        this.formdata = this.crawlform.value;
        this.localService.setformDetails(this.formdata);
        if (res.status === 'completed' || res.status === 'queued') {
          this.scrape = true;
          if (mode === 'all' || mode === 'single') {
            this.startSocket(res.crawl_id);
          } else {
            this.getMarkdown(res.markdown_path);
          }
        }
        this.isLoading = false;
      },
      error: () => {
        this.isLoading = false;
      }
    });
  }

  startSocket(crawlId: string) {
    this.isLoading = true;
    this.socketService.connect(crawlId).pipe(takeUntil(this.destroy$)).subscribe({
      next: (data: any) => {
        this.isLoading = true;
        console.log('Socket Data:', data);
        if (data?.file_path) {
          this.getMarkdown(data.file_path);
        }
      },
      error: (err) => {
        console.error('Socket Error:', err);
      }
    });
  }

  processBatch() {
    const combined = this.socketMessages.join('\n\n');
    this.markdownBlocks.push(combined);
  }


  getMarkdown(path: any) {
    if (this.formdata?.crawl_mode === 'single') {
      this.localService.setCrawlID(path);
    }
    const params = { file_path: path };
    this.apiService.get(URLS.markdown_Details, params).pipe(takeUntil(this.destroy$)).subscribe((res: any) => {
      this.loaderservice.hide()
      console.log('markdownpathclaeed')
      this.isLoading = false;
      const markdownText = res.markdown || res;
      this.markdownBlocks = [
        ...this.markdownBlocks,
        markdownText
      ];
      this.loaderservice.hide()
      this.cd.detectChanges();
      this.isLoading = false;
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
