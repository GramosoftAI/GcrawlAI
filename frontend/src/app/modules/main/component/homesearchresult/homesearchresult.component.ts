import { ChangeDetectorRef, Component } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { Subject, takeUntil } from 'rxjs';
import { URLS } from 'src/app/configs/api.config';
import { ApiService } from 'src/app/services/api.service';
import { LocalStorageService } from 'src/app/services/localstorage-service';
import { marked } from 'marked';
import { QuoteSocketService } from 'src/app/services/websocket.service';
import { ToastrService } from 'ngx-toastr';

@Component({
  selector: 'app-homesearchresult',
  templateUrl: './homesearchresult.component.html',
  styleUrls: ['./homesearchresult.component.scss']
})
export class HomesearchresultComponent {
  private destroy$ = new Subject<void>();
  activeTab: 'markdown' | 'json' = 'markdown';
  tabs = ['Python', 'Node.js', 'Curl'];
  activeTab1 = 'Python';
  markdownData: any;
  crawl_mode: any;
  crawlID: any;
  scrape: boolean = false;
  isLoading: boolean = false;
  unSubscribe$ = new Subject();
  crawlform: FormGroup;
  socketMessages: string[] = [];
  markdownBlocks: string[] = [];

  constructor(private apiService: ApiService, private cd: ChangeDetectorRef, private toastr: ToastrService, private fb: FormBuilder, private localService: LocalStorageService, private socketService: QuoteSocketService) {
    this.crawlform = this.fb.group({
      url: [""],
      crawl_mode: [''],
      button: ['scrape']
    })
  }

  ngOnInit(): void {
    this.crawlID = this.localService.getCrawlID();
    if (!this.scrape && this.crawlID) {
      this.getMarkdown(this.localService.getCrawlID())
    }
  }

  setButton(value: string) {
    this.crawlform.patchValue({
      button: value
    });
  }

  Onsubmit() {
    this.scrapStart();
  }

  scrapStart() {
    debugger
    this.isLoading = true;
    this.localService.clearcrawlID();
    const mode = this.crawlform.value.button === 'scrape' ? 'single' : 'all';
    this.crawl_mode = mode;
    this.crawlform.patchValue({
      crawl_mode: mode
    });
    this.apiService.post(URLS.config, this.crawlform.value).pipe(takeUntil(this.destroy$)).subscribe({
      next: (res: any) => {
        if (res.status === 'completed' || res.status === 'queued') {
          debugger
          this.localService.setCrawlID(res.markdown_path);
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
    debugger
    this.isLoading = true;
    this.socketService.connect(crawlId).pipe(takeUntil(this.destroy$)).subscribe({
      next: (data: any) => {
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
    debugger
    const combined = this.socketMessages.join('\n\n');
    this.markdownBlocks.push(combined);
  }


  getMarkdown(path: any) {
    debugger
    const params = { file_path: path };
    this.apiService.get(URLS.markdown_Details, params).pipe(takeUntil(this.destroy$)).subscribe((res: any) => {
      const markdownText = res.markdown || res;
      this.markdownBlocks = [
        ...this.markdownBlocks,
        markdownText
      ];
      this.cd.detectChanges();
      this.isLoading = false;
    });

  }

  downloadMarkdown(content: string, index: number) {

    const blob = new Blob([content], {
      type: 'text/markdown;charset=utf-8'
    });

    const url = window.URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `report_${index + 1}.md`; // file name

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
