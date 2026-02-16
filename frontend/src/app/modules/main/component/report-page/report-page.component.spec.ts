import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ReportPageComponent } from './report-page.component';

describe('ReportPageComponent', () => {
  let component: ReportPageComponent;
  let fixture: ComponentFixture<ReportPageComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [ReportPageComponent]
    });
    fixture = TestBed.createComponent(ReportPageComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
