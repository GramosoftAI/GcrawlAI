import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CrawlHistoryComponent } from './crawl-history.component';

describe('CrawlHistoryComponent', () => {
  let component: CrawlHistoryComponent;
  let fixture: ComponentFixture<CrawlHistoryComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [CrawlHistoryComponent]
    });
    fixture = TestBed.createComponent(CrawlHistoryComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
