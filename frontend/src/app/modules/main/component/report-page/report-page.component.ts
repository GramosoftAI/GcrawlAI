import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import { marked } from 'marked';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { LocalStorageService } from 'src/app/services/localstorage-service';
import { FormBuilder, FormGroup } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

@Component({
  selector: 'app-report-page',
  templateUrl: './report-page.component.html',
  styleUrls: ['./report-page.component.scss']
})
export class ReportPageComponent implements OnChanges {
  token: any;
  @Input() blocks: string[] = [];
  parsedBlocks: any[] = [];
  reportForm: FormGroup;

  constructor(private sanitizer: DomSanitizer, private route: ActivatedRoute, private router: Router, private localService: LocalStorageService, private Fb: FormBuilder) {
    this.reportForm = this.Fb.group({

    })
  }

  ngOnInit(): void {
    debugger
    this.token = this.localService.getAccessToken();
    this.route.queryParams.subscribe(params => {
      const isLogin = [params['isLogin'] === true];
       console.log('isLogin', isLogin)
    })
    console.log('token', this.token)
  }

  isLogin() {
    debugger
    this.localService.setfirstLogin(true)
    this.router.navigate(['/auth'])
  }

  ngOnChanges(changes: SimpleChanges) {
    debugger
    if (changes['blocks'] && this.blocks?.length) {
      Promise.all(this.blocks.map(md =>
        this.parseMarkdown(md)
      )).then(blocks => {
        this.parsedBlocks = blocks;
      });
    }
  }

  async parseMarkdown(md: string) {
    const lines = md.split('\n');
    const title = lines.find(l => l.startsWith('# '))?.replace('# ', '') || 'Untitled';
    const subtitle = lines.find(l => l.startsWith('## '))?.replace('## ', '') || '';
    const html = await marked(md);
    const urlLine = lines.find(l => l.startsWith('URL:'));
    const url = urlLine ? urlLine.replace('URL:', '').trim() : '';
    return {
      title,
      subtitle,
      html: this.sanitizer.bypassSecurityTrustHtml(html),
      raw: md,
      url
    };

  }


  trackByIndex(index: number) {
    return index;
  }

  download(content: string, index: number) {

    const blob = new Blob([content], {
      type: 'text/markdown;charset=utf-8'
    });

    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `report_${index + 1}.md`;

    a.click();

    URL.revokeObjectURL(url);
  }

  OnSubmit() { }
}
