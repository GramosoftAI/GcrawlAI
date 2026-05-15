import { Component, OnInit } from '@angular/core';
import { AbstractControl, FormBuilder, FormControl, FormGroup, ValidationErrors, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { Subject, takeUntil } from 'rxjs';
import { URLS } from 'src/app/configs/api.config';
import { ApiService } from 'src/app/services/api.service';

@Component({
  selector: 'app-reset-password',
  templateUrl: './reset-password.component.html',
  styleUrls: ['./reset-password.component.scss']
})
export class ResetPasswordComponent implements OnInit {
  passwordForm: FormGroup;
  unSubscribe$ = new Subject();
  hideNewPassword: boolean = true;
  hideConfirmPassword: boolean = true;
  isLoading: boolean = false;
  token: string | null = null;

  constructor(
    private fb: FormBuilder,
    private toastr: ToastrService,
    private apiService: ApiService,
    private router: Router,
    private route: ActivatedRoute
  ) {
    this.passwordForm = this.fb.group(
      {
        newpassword: ['', [Validators.required, Validators.minLength(8), Validators.pattern(/^(?=.*[0-9])(?=.*[!@#$%^&*])[A-Za-z0-9!@#$%^&*]{8,}$/)]],
        confirmpassword: ['', Validators.required]
      },
      { validators: this.passwordMatchValidator }
    );
  }

  ngOnInit(): void {
    this.token = this.route.snapshot.queryParamMap.get('token');
    if (!this.token) {
      this.toastr.error('Invalid or missing reset token');
      this.router.navigate(['']);
    }
  }

  passwordMatchValidator(control: AbstractControl): ValidationErrors | null {
  const password = control.get('newpassword')?.value;
  const confirmPassword = control.get('confirmpassword')?.value;

  if (password !== confirmPassword) {
    control.get('confirmpassword')?.setErrors({ mismatch: true });
    return { mismatch: true };
  }

  // ✅ Add this — clears mismatch error when they match
  const confirmControl = control.get('confirmpassword');
  if (confirmControl?.hasError('mismatch')) {
    const errors = { ...confirmControl.errors };
    delete errors['mismatch'];
    confirmControl.setErrors(Object.keys(errors).length ? errors : null);
  }

  return null;
}

  toggleNewPassword(): void {
    this.hideNewPassword = !this.hideNewPassword;
  }

  toggleConfirmPassword(): void {
    this.hideConfirmPassword = !this.hideConfirmPassword;
  }

  resetPasswordSubmit() {
    if (this.passwordForm.invalid || !this.token) {
      this.passwordForm.markAllAsTouched();
      return;
    }

    this.isLoading = true;
    const payload = {
      token: this.token,
      new_password: this.passwordForm.value.newpassword
    };

    this.apiService.post(URLS.resetPassword, payload).pipe(takeUntil(this.unSubscribe$)).subscribe({
      next: (res: any) => {
        this.isLoading = false;
        if (res.status === "success") {
          this.toastr.success('Password reset successfully. You can now login.');
          this.router.navigate(['/auth/signin']);
        } else {
          this.toastr.error(res.message || 'Failed to reset password');
        }
      },
      error: () => {
        this.isLoading = false;
        this.toastr.error('An error occurred');
      }
    });
  }

  ngOnDestroy() {
    this.unSubscribe$.next(null);
    this.unSubscribe$.complete();
  }
}
