import { Component, Input, OnInit, OnChanges, SimpleChanges, Output, EventEmitter } from '@angular/core';
import { OwlOptions } from 'ngx-owl-carousel-o';
import { FormBuilder, FormGroup } from '@angular/forms';
import { Subject, takeUntil } from 'rxjs';
import { URLS } from 'src/app/configs/api.config';
import { ApiService } from 'src/app/services/api.service';
import { LocalStorageService } from 'src/app/services/localstorage-service';

@Component({
  selector: 'app-crawl-history',
  templateUrl: './crawl-history.component.html',
  styleUrls: ['./crawl-history.component.scss']
})
export class CrawlHistoryComponent implements OnInit, OnChanges {
  private destroy$ = new Subject<void>();
  historyForm: FormGroup;
  historyData: any[] = [];
  crawlId: any;
  userID: any;
  historyPath: any;
  @Input() scrapper: any;
  @Output() reportClicked = new EventEmitter<any>();

  customOptions: OwlOptions = {
    loop: false,
    mouseDrag: true,
    touchDrag: true,
    pullDrag: true,
    dots: false,
    navSpeed: 700,
    navText: ['<i class="bi bi-chevron-left"></i>', '<i class="bi bi-chevron-right"></i>'],
    responsive: {
      0: { items: 1 },
      600: { items: 2 },
      900: { items: 3 }
    },
    nav: true,
    margin: 20
  };

  constructor(private apiService: ApiService, private fb: FormBuilder, private localService: LocalStorageService) {
    this.historyForm = this.fb.group({
      crawl_id: [0]
    })
  }

  ngOnInit(): void {
    this.userID = this.localService.getUserDetails();
    console.log(this.userID, "user id from local storage");
    if (this.userID && this.scrapper) {
      this.getuserHistoryid();
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['scrapper'] && changes['scrapper'].currentValue === true) {
      // Refresh the history when a new crawl/scrape finishes and `scrapper` switches to true
      if (this.userID) {
        this.getuserHistoryid();
      }
    }
  }

  getuserHistoryid() {
    debugger
    this.userID = this.localService.getUserDetails();
    const User_id = this.userID?.user?.user_id;
    if (!User_id) return;
    this.historyData = [];
    const urlWithId = `${URLS.userhistory_path_id}/${User_id}`;
    this.apiService.get(urlWithId, null, true).pipe(takeUntil(this.destroy$)).subscribe({
      next: (res: any) => {
        if (res) {
          this.historyData = res.crawls;
        }
      }
    });
  }

  getReport(crawlId: any) {
    debugger
    const crawl_id = crawlId;
    if (!crawl_id) return;
    const urlWithId = `${URLS.user_history}/${crawl_id}`;
    this.apiService.get(urlWithId, null, true).pipe(takeUntil(this.destroy$)).subscribe({
      next: (res: any) => {
        if (res && res.status === 'success') {
          this.reportClicked.emit(res);
        }
      }
    });
  }

  getMode(mode: string): string {
    if (mode === 'all') return 'Crawl';
    if (mode === 'single') return 'Scrape';
    if (mode === 'links') return 'Link';
    return mode || 'Unknown';
  }

  getFormats(item: any): string {
    const formats = [];
    if (item.markdown) formats.push('Markdown');
    if (item.html) formats.push('HTML');
    if (item.seo) formats.push('SEO');
    if (item.screenshot) formats.push('Screenshot');
    return formats.length > 0 ? formats.join(', ') : 'None';
  }
}