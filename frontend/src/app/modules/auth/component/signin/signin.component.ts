import { Component, ViewChild } from '@angular/core';
import { AbstractControl, FormBuilder, FormControl, FormGroup, ValidationErrors, Validators } from '@angular/forms';
import { MatDialog } from '@angular/material/dialog';
import { Router } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { Subject, takeUntil } from 'rxjs';
import { URLS } from 'src/app/configs/api.config';
import { passwordValidator } from 'src/app/directives/form-validators.directive';
import { OtpModalComponent } from 'src/app/modules/shared/component/otp-modal/otp-modal.component';
import { ApiService } from 'src/app/services/api.service';
import { AuthService } from 'src/app/services/auth.service';
import { DependencyService } from 'src/app/services/dependency.service';
import { LocalStorageService } from 'src/app/services/localstorage-service';

@Component({
  selector: 'app-signin',
  templateUrl: './signin.component.html',
  styleUrls: ['./signin.component.scss']
})
export class SigninComponent {
  loginForm: FormGroup;
  passwordForm: FormGroup;
  unSubscribe$ = new Subject();
  hideNewPassword: boolean = true;
  hideConfirmPassword: boolean = true;
  hidePassword: boolean = true;
  Isforgot: boolean = false;
  firstLogin: any;
  activeTab: 'login' | 'signup' = 'signup';
  jsonData = JSON.stringify({
    sensor_id: "ANALYTICS_01",
    status: "ACTIVE",
    metrics: { cpu: "42%", latency: "12ms", throughput: "1.2gbps" },
    nodes: ["us-east", "eu-west", "ap-south"]
  }, null, 2);
  @ViewChild(OtpModalComponent) childOTP!: OtpModalComponent;
  logs = new Array(20).fill("FETCHING_BLOCK_RESOURCES... SUCCESS");

  constructor(private fb: FormBuilder, private toastr: ToastrService, private localService: LocalStorageService, private apiService: ApiService, private authService: AuthService, private router: Router, public ds: DependencyService, public dialog: MatDialog) {
    this.loginForm = this.fb.group({
      email: new FormControl('', [Validators.required]),
      password: new FormControl('', [Validators.required, Validators.minLength(8), Validators.pattern(/^(?=.*[0-9])(?=.*[!@#$%^&*])[A-Za-z0-9!@#$%^&*]{8,}$/)]),
      name: new FormControl('', [Validators.required]),
      firstLogin: new FormControl(false, [Validators.required])
    });

    this.passwordForm = this.fb.group(
      {
        newpassword: ['', [Validators.required, Validators.minLength(8), Validators.pattern(/^(?=.*[0-9])(?=.*[!@#$%^&*])[A-Za-z0-9!@#$%^&*]{8,}$/)]],
        confirmpassword: ['', Validators.required]
      },
      { validators: this.passwordMatchValidator }
    );
  }

  ngOnInit(): void {
    this.firstLogin = this.localService.getfirstLogin();

    this.loginForm.get('email')?.valueChanges.subscribe(email => {
      if (email && email.includes('@')) {
        const username = email.split('@')[0];
        const shortName = username.substring(0, 10);
        this.loginForm.patchValue({
          name: shortName
        });
      }
    });
  }

  passwordMatchValidator(control: AbstractControl): ValidationErrors | null {
    const password = control.get('newpassword')?.value;
    const confirmPassword = control.get('confirmpassword')?.value;

    if (password !== confirmPassword) {
      control.get('confirmpassword')?.setErrors({ mismatch: true });
      return { mismatch: true };
    }

    return null;
  }

  togglePassword(): void {
    this.hidePassword = !this.hidePassword;
  }

  toggleNewPassword(): void {
    this.hideNewPassword = !this.hideNewPassword;
  }

  toggleConfirmPassword(): void {
    this.hideConfirmPassword = !this.hideConfirmPassword;
  }

  get f() { return this.loginForm.controls; }

  OnSubmit() {
    if (this.activeTab === 'login') {
      this.loginSubmit();
    } else {
      this.signUpSubmit();
    }
  }

  loginSubmit() {
    if (this.loginForm.invalid) {
      return
    }
    this.apiService.post(URLS.signin, this.loginForm.value, { type: 'NT' }, this.loginForm.value.user_type == 'V' ? 'TRUE' : 'FALSE').pipe((takeUntil(this.unSubscribe$))).subscribe((res: any) => {
      if (res.success === true) {
        this.authService.login(res);
        console.log('loginformvalues', this.loginForm.value)
      };
    })
  }

  signUpSubmit() {
    if (this.loginForm.invalid) {
      return
    }
    this.apiService.post(URLS.signup, this.loginForm.value, { type: 'NT' }, this.loginForm.value.user_type == 'V' ? 'TRUE' : 'FALSE').pipe((takeUntil(this.unSubscribe$))).subscribe((res: any) => {
      if (res.success === true) {
        this.openOtpModal();
      } else {
        this.toastr.error('error', res.detail)
      };
    })
  }

  openOtpModal() {
    ($('#OTPModel') as any).modal('show');
  }

  onOtpSubmit(otp: string) {
    this.validateOtp(otp);
  }

  validateOtp(otp: string) {
    const payload = {
      email: this.loginForm.value.email,
      otp: otp
    };

    this.apiService.post(URLS.verifyOtp, payload, { type: 'LO' }, 'TRUE').pipe(takeUntil(this.unSubscribe$)).subscribe((res: any) => {
      if (res) {
        this.childOTP.clearOtp();
        this.activeTab = 'login';
      } else {
        this.childOTP.isOTPInvalid = true;
      }
    });
  }

  changePassword() { }

  forgot() {
    this.Isforgot = true;
  }

  ngOnDestroy() {
    this.unSubscribe$?.unsubscribe();
  }
}
