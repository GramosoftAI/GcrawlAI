import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import { marked } from 'marked';
import * as XLSX from 'xlsx';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { LocalStorageService } from 'src/app/services/localstorage-service';
import { FormArray, FormBuilder, FormControl, FormGroup } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import * as JSZip from 'jszip';
import { ToastrService } from 'ngx-toastr';
import { Clipboard } from '@angular/cdk/clipboard';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from 'src/app/services/api.service';
import { URLS } from 'src/app/configs/api.config';
import { Subject, takeUntil } from 'rxjs';

@Component({
  selector: 'app-report-page',
  templateUrl: './report-page.component.html',
  styleUrls: ['./report-page.component.scss']
})
export class ReportPageComponent implements OnChanges {
  token: any;
  formValues: any;
  userdetails: any;
  @Input() blocks: any[] = [];
  @Input() formsvalue: any;
  @Input() isCompleted: boolean = false;
  parsedBlocks: any[] = [];
  reportForm: FormGroup;
  activeSeoTab: string = 'xlsx';
  activeTab: string = 'pills-markdown';
  unSubscribe$ = new Subject();
  isFirstSelection: boolean = true;
  issueList = [
    'Missing content',
    'Bot protections',
    'Formatting issues'
  ];
  private parsedCache = new Map<any
    , any>();

  constructor(private fb: FormBuilder, private snackBar: MatSnackBar, private clipboard: Clipboard, private sanitizer: DomSanitizer, private toastr: ToastrService, private router: Router, private localService: LocalStorageService, private Fb: FormBuilder, private apiService: ApiService) {
    this.reportForm = this.fb.group({
      url_affected: [''],
      email: [''],
      issue_related_to: this.fb.array([]),
      other_issue: [''],
      explanation: ['']
    });
  }

  ngOnInit(): void {
    this.userdetails = this.localService.getUserDetails();
    this.token = this.localService.getAccessToken();
    this.formValues = this.localService.getformDetails();
    this.reportForm.patchValue({
      url_affected: this.formValues?.url,
      email: this.userdetails?.user?.email
    });
    this.reportForm.get('url_affected')?.disable();
    this.reportForm.get('email')?.disable();
  }

  get issues(): FormArray {
    return this.reportForm.get('issue_related_to') as FormArray;
  }

  onIssueChange(event: any) {

    const value = event.target.value;

    if (event.target.checked) {
      this.issues.push(new FormControl(value));
    } else {
      const index = this.issues.controls
        .findIndex(ctrl => ctrl.value === value);

      if (index !== -1) {
        this.issues.removeAt(index);
      }
    }
  }

  submitReport() {
    const formValue = this.reportForm.getRawValue();
    let issues = [...formValue.issue_related_to];
    if (formValue.other_issue &&
      formValue.other_issue.trim() !== '') {
      issues.push(formValue.other_issue.trim());
    }

    const payload = {
      url_affected: formValue.url_affected,
      email: formValue.email,
      issue_related_to: issues,
      explanation: formValue.explanation
    };
    // console.log(payload);
    this.apiService.post(URLS.report_Issue, payload, { type: 'NT' }).pipe(takeUntil(this.unSubscribe$)).subscribe((res: any) => {
      if (res.status === 'success') {
        ($('#exampleModal') as any).modal('hide');
        this.toastr.success(res.message);
        this.reportForm.reset();
        this.issues.clear();
      } else {
        this.toastr.error('Failed');
      }
    });
  }

  isLogin() {
    this.localService.setfirstLogin(true)
    this.router.navigate(['/login'])
  }

  ngOnChanges(changes: SimpleChanges) {
    this.formsvalue = this.formsvalue
    this.localService.setformDetails(this.formsvalue)

    // If blocks are reset (new crawl started), reset selection flag
    if (changes['blocks'] && (changes['blocks'].currentValue?.length === 0 || changes['blocks'].firstChange)) {
      this.isFirstSelection = true;
    }

    if (this.formsvalue && this.isFirstSelection) {
      this.setDefaultTab();
      this.isFirstSelection = false;
    }

    if (changes['blocks'] && this.blocks?.length) {
      if (changes['blocks'].currentValue.length === 0) {
        this.parsedCache.clear();
        this.parsedBlocks = [];
      } else {
        const newParsedBlocks: any[] = [];
        const promises = this.blocks.map(async (block) => {
          if (this.parsedCache.has(block)) {
            return this.parsedCache.get(block);
          }
          // The block might already be fully parsed out if coming from historical state
          // where homesearchresult component maps it manually into full objects. 
          // If the block is an object and already has `html`/`raw`/etc., we might not need full parsing.
          // But `parseBlock` handles those object blocks too, so we pass it gracefully.
          const parsed = await this.parseBlock(block);
          this.parsedCache.set(block, parsed);
          return parsed;
        });

        Promise.all(promises).then(parsed => {
          this.parsedBlocks = parsed;
          if (this.isCrawlMode()) {
            this.snackBar.open(
              `Total Pages: ${this.parsedBlocks.length} / 10`,
              'Close',
              {
                duration: 8000,
                horizontalPosition: 'center',
                verticalPosition: 'bottom'
              }
            );
          }
        });
      }
    }
  }

  setDefaultTab() {
    if (this.formsvalue.enable_ss) {
      this.activeTab = 'pills-screenshot';
    } else if (this.formsvalue.enable_md) {
      this.activeTab = 'pills-markdown';
    } else if (this.formsvalue.enable_summary) {
      this.activeTab = 'pills-summary';
    } else if (this.formsvalue.enable_links) {
      this.activeTab = 'pills-links';
    } else if (this.formsvalue.enable_html) {
      this.activeTab = 'pills-html';
    } else if (this.formsvalue.enable_seo) {
      this.activeTab = 'pills-seo';
    } else if (this.formsvalue.enable_json) {
      this.activeTab = 'pills-json';
    }
  }

  setActiveTab(tabId: string) {
    this.activeTab = tabId;
  }

  async parseBlock(block: any) {
    debugger
    // console.log('Parsing block:', block);
    const md = typeof block === 'string' ? block : (block.markdown || block.raw || block.content || '');
    const ss = typeof block === 'string' ? null : block.screenshot || null;
    const htmlContent = typeof block === 'string' ? null : block.engineHtml || null;
    let linksContent = typeof block === 'string' ? null : block.links || null;
    let linksCount = 0;
    if (linksContent) {
      const parsedLinks = linksContent.split('\n').filter((l: string) => l.trim().length > 0);
      linksCount = parsedLinks.length;
      linksContent = parsedLinks.map((link: string, idx: number) => {
        const cleanLink = link.replace(/^[-*]\s+/, '').replace(/^\d+\.\s+/, '');
        return `${idx + 1}. ${cleanLink}`;
      }).join('\n');
    }
    const summaryContent = typeof block === 'string' ? null : block.summary || null;

    // SEO sub-formats
    const seo_md = typeof block === 'string' ? null : block.seo_md || null;
    const seo_json = typeof block === 'string' ? null : block.seo_json || null;
    const seo_xlsx = typeof block === 'string' ? null : block.seo_xlsx || null;

    const lines = md.split('\n');
    const title = lines.find((l: string) => l.startsWith('# '))?.replace('# ', '') || 'Untitled';
    const subtitle = lines.find((l: string) => l.startsWith('## '))?.replace('## ', '') || '';
    const renderedMd = await marked(md);

    // Render SEO Markdown if available
    let renderedSeoMd = null;
    if (seo_md) {
      renderedSeoMd = seo_md;
    }

    const urlLine = lines.find((l: string) => l.startsWith('URL:'));
    const url = urlLine ? urlLine.replace('URL:', '').trim() : '';

    let xlsxTable: any[] = [];
    if (seo_xlsx) {
      try {
        let base64Data = seo_xlsx;
        if (typeof seo_xlsx === 'string') {
          // Strip data URI prefix if present
          base64Data = seo_xlsx.includes('base64,') ? seo_xlsx.split('base64,')[1] : seo_xlsx;
          const workbook = XLSX.read(base64Data, { type: 'base64' });
          const firstSheetName = workbook.SheetNames[0];
          const worksheet = workbook.Sheets[firstSheetName];
          xlsxTable = XLSX.utils.sheet_to_json(worksheet);
        } else {
          this.toastr.warning('seo_xlsx is not a string:', typeof seo_xlsx);
        }
      } catch (e) {
        console.error('Error parsing XLSX:', e);
      }
    }

    // Parse JSON directly to build comprehensive table rows
    let parsedJsonData = null;
    if (seo_json) {
      try {
        parsedJsonData = typeof seo_json === 'string' ? JSON.parse(seo_json) : seo_json;
        // Unwrap nested data object if it exists (e.g. { url: "...", data: { title: "..." } })
        if (parsedJsonData && parsedJsonData.data) {
          parsedJsonData = parsedJsonData.data;
        }
      } catch (e) {
        console.error('Error parsing SEO JSON:', e);
      }
    }

    let finalTitle = title;
    let finalUrl = url;

    if (typeof block === 'object' && block.title) {
      finalTitle = block.title;
    } else if (finalTitle === 'Untitled' || !finalTitle) {
      if (parsedJsonData?.title) {
        finalTitle = parsedJsonData.title;
      } else if (xlsxTable && xlsxTable.length > 0 && xlsxTable[0].title) {
        finalTitle = xlsxTable[0].title;
      } else if (renderedSeoMd) {
        const seoLines = renderedSeoMd.split('\n');
        const titleLine = seoLines.find((l: string) => l.startsWith('Title:'));
        if (titleLine) finalTitle = titleLine.replace('Title:', '').trim();
      }
    }

    if (!finalUrl) {
      if (parsedJsonData?.url) {
        finalUrl = parsedJsonData.url;
      } else if (xlsxTable && xlsxTable.length > 0 && xlsxTable[0].url) {
        finalUrl = xlsxTable[0].url;
      } else if (renderedSeoMd) {
        const seoLines = renderedSeoMd.split('\n');
        const urlLine = seoLines.find((l: string) => l.startsWith('URL:'));
        if (urlLine) finalUrl = urlLine.replace('URL:', '').trim();
      }
    }

    return {
      title: finalTitle,
      subtitle,
      html: this.sanitizer.bypassSecurityTrustHtml(renderedMd),
      raw: md,
      screenshot: ss,
      rawHtml: htmlContent,
      links: linksContent,
      linksCount: linksCount,
      summary: summaryContent,
      seo: {
        md: renderedSeoMd,
        raw_md: seo_md,
        json: seo_json,
        parsedJsonData: parsedJsonData,
        xlsx: seo_xlsx,
        xlsxTable: xlsxTable
      },
      url: finalUrl
    };
  }

  get consolidatedXlsxTable(): { headers: string[], rows: any[] } {
    if (!this.parsedBlocks || this.parsedBlocks.length === 0) return { headers: [], rows: [] };

    let headersSet = new Set<string>();
    let allDataRows: any[] = [];

    this.parsedBlocks.forEach(block => {
      // Prioritize raw JSON metric data since it maps accurately
      if (block.seo?.parsedJsonData) {
        const rowData = { ...block.seo.parsedJsonData };
        Object.keys(rowData).forEach(key => {
          if (Array.isArray(rowData[key])) {
            rowData[key] = rowData[key].join(', ');
          }
          headersSet.add(key);
        });
        allDataRows.push(rowData);
      }
      // Fallback to parsed XLSX Table
      else if (block.seo?.xlsxTable && block.seo.xlsxTable.length > 0) {
        block.seo.xlsxTable.forEach((row: any) => {
          allDataRows.push(row);
          Object.keys(row).forEach(k => headersSet.add(k));
        });
      }
    });

    return {
      headers: Array.from(headersSet),
      rows: allDataRows
    };
  }

  parseSeoMd(md: string): { label: string, value: string }[] {
    if (!md) return [];
    // Regular expression to handle "Label: Value" format, ignoring header lines starting with #
    return md.split('\n')
      .map(line => line.trim())
      .filter(line => line.includes(':') && !line.startsWith('#'))
      .map(line => {
        const index = line.indexOf(':');
        return {
          label: line.substring(0, index).trim(),
          value: line.substring(index + 1).trim()
        };
      })
      .filter(item => item.label && item.value);
  }

  isScrapeMode(): boolean {
    return this.formsvalue?.button === 'scrape';
  }

  isCrawlMode(): boolean {
    return this.formsvalue?.button === 'crawl';
  }


  trackByIndex(index: number) {
    return index;
  }

  download(content: string, index: number, format: 'md' | 'json' | 'xlsx' | 'html' | 'png' = 'md', customName?: string) {

    let type = 'text/markdown;charset=utf-8';
    let ext = 'md';
    let data: any = content;

    if (format === 'json') {
      type = 'application/json;charset=utf-8';
      ext = 'json';
    } else if (format === 'html') {
      type = 'text/html;charset=utf-8';
      ext = 'html';
    } else if (format === 'xlsx' || format === 'png') {
      if (format === 'xlsx') {
        type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
        ext = 'xlsx';
      } else {
        type = 'image/png';
        ext = 'png';
      }

      // Decode base64 if it's binary data
      try {
        // Strip data URI prefix if present
        const base64Data = content.includes('base64,') ? content.split('base64,')[1] : content;
        const byteCharacters = atob(base64Data);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
          byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        data = new Uint8Array(byteNumbers);
      } catch (e) {
        console.error(`Failed to decode ${format} base64:`, e);
      }
    }

    const blob = new Blob([data], {
      type: type
    });

    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;

    // Use customized name or derive from first page title
    const rawTitle = this.parsedBlocks[0]?.title ? this.parsedBlocks[0]?.title : this.parsedBlocks[0]?.url || 'report';
    const sanitizedTitle = rawTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase();
    const fileName = customName || `${sanitizedTitle}_${index + 1}.${ext}`;

    a.download = fileName;

    a.click();
    URL.revokeObjectURL(url);
  }

  downloadConsolidatedXlsx() {
    if (!this.consolidatedXlsxTable || this.consolidatedXlsxTable.rows.length === 0) return;

    // Create worksheet from JSON array
    const ws: XLSX.WorkSheet = XLSX.utils.json_to_sheet(this.consolidatedXlsxTable.rows);
    const wb: XLSX.WorkBook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'SEO Report');

    // Generate XLSX file as base64 and use existing download helper
    const wbout = XLSX.write(wb, { bookType: 'xlsx', type: 'base64' });

    const rawTitle = this.parsedBlocks[0]?.title ? this.parsedBlocks[0]?.title : this.parsedBlocks[0]?.url || 'report';
    const sanitizedTitle = rawTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase();

    this.download(wbout, 0, 'xlsx', `${sanitizedTitle}_seo.xlsx`);
  }

  downloadAllHtml() {
    if (!this.parsedBlocks || this.parsedBlocks.length === 0) return;

    const allHtml = this.parsedBlocks
      .map((block, i) => `<!-- PAGE ${i + 1}: ${block.url} -->\n${block.rawHtml}\n\n`)
      .join('---\n\n');

    const rawTitle = this.parsedBlocks[0]?.title ? this.parsedBlocks[0]?.title : this.parsedBlocks[0]?.url || 'report';
    const sanitizedTitle = rawTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase();

    this.download(allHtml, 0, 'html', `${sanitizedTitle}_all_pages.html`);
  }

  downloadAllSeoMd() {
    if (!this.parsedBlocks || this.parsedBlocks.length === 0) return;
    const allSeoMd = this.parsedBlocks
      .filter(block => block.seo?.raw_md)
      .map((block, i) => `<!-- PAGE ${i + 1}: ${block.url} -->\n${block.seo.raw_md}\n\n`)
      .join('---\n\n');
    if (allSeoMd) {
      const rawTitle = this.parsedBlocks[0]?.title ? this.parsedBlocks[0]?.title : this.parsedBlocks[0]?.url || 'report';
      const sanitizedTitle = rawTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase();
      this.download(allSeoMd, 0, 'md', `${sanitizedTitle}_seo.md`);
    }
  }

  downloadAllSeoJson() {
    if (!this.parsedBlocks || this.parsedBlocks.length === 0) return;
    const allSeoJson = this.parsedBlocks
      .filter(block => block.seo?.json)
      .map(block => {
        try {
          return typeof block.seo.json === 'string' ? JSON.parse(block.seo.json) : block.seo.json;
        } catch (e) {
          return block.seo.json;
        }
      });
    if (allSeoJson.length > 0) {
      const rawTitle = this.parsedBlocks[0]?.title ? this.parsedBlocks[0]?.title : this.parsedBlocks[0]?.url || 'report';
      const sanitizedTitle = rawTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase();
      this.download(JSON.stringify(allSeoJson, null, 2), 0, 'json', `${sanitizedTitle}_seo.json`);
    }
  }

  async generateZip() {
    if (!this.parsedBlocks || this.parsedBlocks.length === 0) return;

    const zip = new JSZip();
    const rawTitle = this.parsedBlocks[0]?.title ? this.parsedBlocks[0]?.title : this.parsedBlocks[0]?.url || 'report';
    const sanitizedTitle = rawTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase();
    const folder = zip.folder(sanitizedTitle);

    if (!folder) return;

    // 1. Markdown
    if (this.formsvalue?.enable_md) {
      const allMd = this.parsedBlocks
        .filter(block => block.raw)
        .map((block, i) => `<!-- PAGE ${i + 1}: ${block.url} -->\n${block.raw}\n\n`)
        .join('---\n\n');
      if (allMd) folder.file('report.md', allMd);
    }

    // 2. HTML
    if (this.formsvalue?.enable_html) {
      const allHtml = this.parsedBlocks
        .filter(block => block.rawHtml)
        .map((block, i) => `<!-- PAGE ${i + 1}: ${block.url} -->\n${block.rawHtml}\n\n`)
        .join('---\n\n');
      if (allHtml) folder.file('full_pages.html', allHtml);
    }

    // 3. Links
    if (this.formsvalue?.enable_links) {
      const allLinks = this.parsedBlocks
        .filter(block => block.links)
        .map((block, i) => `<!-- LINKS ${i + 1}: ${block.url} -->\n${block.links}\n\n`)
        .join('---\n\n');
      if (allLinks) folder.file('extracted_links.txt', allLinks);
    }

    // 4. Summary
    if (this.formsvalue?.enable_summary) {
      const allSummary = this.parsedBlocks
        .filter(block => block.summary)
        .map((block, i) => `<!-- SUMMARY ${i + 1}: ${block.url} -->\n${block.summary}\n\n`)
        .join('---\n\n');
      if (allSummary) folder.file('summary.md', allSummary);
    }

    // 5. SEO
    if (this.formsvalue?.enable_seo) {
      const seoFolder = folder.folder('seo');
      if (seoFolder) {
        // MD
        const allSeoMd = this.parsedBlocks
          .filter(block => block.seo?.raw_md)
          .map((block, i) => `<!-- SEO PAGE ${i + 1}: ${block.url} -->\n${block.seo.raw_md}\n\n`)
          .join('---\n\n');
        if (allSeoMd) seoFolder.file('seo_report.md', allSeoMd);

        // JSON
        const allSeoJson = this.parsedBlocks
          .filter(block => block.seo?.json)
          .map(block => {
            try { return typeof block.seo.json === 'string' ? JSON.parse(block.seo.json) : block.seo.json; }
            catch (e) { return block.seo.json; }
          });
        if (allSeoJson.length > 0) seoFolder.file('seo_report.json', JSON.stringify(allSeoJson, null, 2));

        // XLSX
        if (this.consolidatedXlsxTable.rows.length > 0) {
          const ws = XLSX.utils.json_to_sheet(this.consolidatedXlsxTable.rows);
          const wb = XLSX.utils.book_new();
          XLSX.utils.book_append_sheet(wb, ws, 'SEO Report');
          const wbout = XLSX.write(wb, { bookType: 'xlsx', type: 'array' });
          seoFolder.file('seo_report.xlsx', wbout);
        }
      }
    }

    // 6. Screenshots
    if (this.formsvalue?.enable_ss) {
      const ssFolder = folder.folder('screenshots');
      if (ssFolder) {
        this.parsedBlocks.forEach((block, i) => {
          if (block.screenshot) {
            const base64Data = block.screenshot.includes('base64,') ? block.screenshot.split('base64,')[1] : block.screenshot;
            ssFolder.file(`screenshot_${i + 1}.png`, base64Data, { base64: true });
          }
        });
      }
    }

    const blob = await zip.generateAsync({ type: 'blob' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${sanitizedTitle}_complete.zip`;
    a.click();
    URL.revokeObjectURL(url);
  }

  downloadDynamic() {
    if (!this.token) {
      this.isLogin();
      return;
    }

    if (!this.parsedBlocks || this.parsedBlocks.length === 0) return;
    const enabledCount = [
      this.formsvalue?.enable_md,
      this.formsvalue?.enable_html,
      this.formsvalue?.enable_ss,
      this.formsvalue?.enable_seo,
      this.formsvalue?.enable_links,
      this.formsvalue?.enable_summary
    ].filter(Boolean).length;

    if (enabledCount > 1) {
      this.generateZip();
      return;
    }

    switch (this.activeTab) {
      case 'pills-markdown':
        this.downloadTextConsolidated('raw', 'md', 'Markdown');
        break;
      case 'pills-html':
        this.downloadAllHtml();
        break;
      case 'pills-links':
        this.downloadTextConsolidated('links', 'md', 'Links');
        break;
      case 'pills-summary':
        this.downloadTextConsolidated('summary', 'md', 'Summary');
        break;
      case 'pills-json':
        this.downloadAllSeoJson();
        break;
      case 'pills-seo':
        if (this.activeSeoTab === 'xlsx') {
          this.downloadConsolidatedXlsx();
        } else if (this.activeSeoTab === 'md') {
          this.downloadAllSeoMd();
        } else if (this.activeSeoTab === 'json') {
          this.downloadAllSeoJson();
        }
        break;
      case 'pills-screenshot':
        if (this.parsedBlocks[0]?.screenshot) {
          this.download(this.parsedBlocks[0].screenshot, 0, 'png');
        }
        break;
    }
  }

  private downloadTextConsolidated(field: string, ext: 'md' | 'html', label: string) {
    const content = this.parsedBlocks
      .filter(block => block[field])
      .map((block, i) => `<!-- ${label.toUpperCase()} ${i + 1}: ${block.url} -->\n${block[field]}\n\n`)
      .join('---\n\n');

    if (content) {
      const rawTitle = this.parsedBlocks[0]?.title ? this.parsedBlocks[0]?.title : this.parsedBlocks[0]?.url || 'report';
      const sanitizedTitle = rawTitle.replace(/[^a-z0-9]/gi, '_').toLowerCase();
      this.download(content, 0, ext, `${sanitizedTitle}_${label.toLowerCase()}.md`);
    }
  }

  OnSubmit() { }

  setSeoTab(type: string) {
    this.activeSeoTab = type;
  }

  copiedItem: string | null = null;

  copyToClipboard(text: string, identifier: string) {
    if (!text || text === '-') return;

    const successful = this.clipboard.copy(text);
    if (successful) {
      this.toastr.success('Copied to clipboard');
      this.copiedItem = identifier;
      setTimeout(() => {
        if (this.copiedItem === identifier) {
          this.copiedItem = null;
        }
      }, 2000); // Reset icon after 2 seconds
    } else {
      this.toastr.error('Failed to copy');
    }
  }

  isLongData(text: any): boolean {
    if (!text) return false;
    return text.toString().length > 100;
  }
}
