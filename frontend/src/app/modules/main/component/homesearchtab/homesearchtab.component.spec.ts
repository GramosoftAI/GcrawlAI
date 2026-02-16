import { ComponentFixture, TestBed } from '@angular/core/testing';

import { HomesearchtabComponent } from './homesearchtab.component';

describe('HomesearchtabComponent', () => {
  let component: HomesearchtabComponent;
  let fixture: ComponentFixture<HomesearchtabComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [HomesearchtabComponent]
    });
    fixture = TestBed.createComponent(HomesearchtabComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
