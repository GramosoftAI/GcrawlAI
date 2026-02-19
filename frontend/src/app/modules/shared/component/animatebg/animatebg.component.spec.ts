import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AnimatebgComponent } from './animatebg.component';

describe('AnimatebgComponent', () => {
  let component: AnimatebgComponent;
  let fixture: ComponentFixture<AnimatebgComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [AnimatebgComponent]
    });
    fixture = TestBed.createComponent(AnimatebgComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
