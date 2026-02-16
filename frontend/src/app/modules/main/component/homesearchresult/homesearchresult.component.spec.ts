import { ComponentFixture, TestBed } from '@angular/core/testing';

import { HomesearchresultComponent } from './homesearchresult.component';

describe('HomesearchresultComponent', () => {
  let component: HomesearchresultComponent;
  let fixture: ComponentFixture<HomesearchresultComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [HomesearchresultComponent]
    });
    fixture = TestBed.createComponent(HomesearchresultComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
