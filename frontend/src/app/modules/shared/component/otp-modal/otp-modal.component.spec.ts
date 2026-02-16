import { ComponentFixture, TestBed } from '@angular/core/testing';

import { OtpModalComponent } from './otp-modal.component';

describe('OtpModalComponent', () => {
  let component: OtpModalComponent;
  let fixture: ComponentFixture<OtpModalComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [OtpModalComponent]
    });
    fixture = TestBed.createComponent(OtpModalComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
