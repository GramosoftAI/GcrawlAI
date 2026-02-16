import { Component, EventEmitter, Input, Output, ViewChild } from '@angular/core';
import { NgOtpInputComponent } from 'ng-otp-input';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-otp-modal',
  templateUrl: './otp-modal.component.html',
  styleUrls: ['./otp-modal.component.scss']
})
export class OtpModalComponent {
  @ViewChild(NgOtpInputComponent) otpInput!: NgOtpInputComponent;
  @ViewChild('ngOtpInput', { static: false }) ngOtpInput: any;
  otp: string = '';
  isValidOTP: boolean = false;
  counter: number = 120;
  countDown!: Subscription;
  isOTPInvalid: boolean = false;

  @Output() validateEvent = new EventEmitter<string>();
  @Output() resendOtpEvent = new EventEmitter();
  @Input() otpFor: string = '';

  constructor() { }

  ngOnInit(): void {
  }

  getOTP(): void {
    this.validateEvent.emit(this.otp);

  }

  resendOTP() {
    this.otp = '';
    this.ngOtpInput.setValue('')
    this.countDown.unsubscribe();
    this.resendOtpEvent.emit();
  }

  onOtpChange(event: string) {
    event.length === 5 ? this.isValidOTP = true : this.isValidOTP = false;
    this.otp = event;
  }

  validate(): void {
    this.isOTPInvalid = false;
    this.validateEvent.emit(this.otp);
  }

  clearOtp() {
    (<any>$('#OTPModel')).modal('hide');
    if (this.otpInput) {
      this.otpInput.setValue('');
      this.otpInput['clearInput']();
    }
    this.otp = '';
    this.isValidOTP = false;
    this.isOTPInvalid = false;
    // this.countDown.unsubscribe();
  }
}
