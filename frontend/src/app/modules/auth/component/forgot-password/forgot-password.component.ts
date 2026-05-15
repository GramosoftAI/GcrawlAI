import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormControl, FormGroup, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { Subject, takeUntil } from 'rxjs';
import { URLS } from 'src/app/configs/api.config';
import { ApiService } from 'src/app/services/api.service';

@Component({
  selector: 'app-forgot-password',
  templateUrl: './forgot-password.component.html',
  styleUrls: ['./forgot-password.component.scss']
})
export class ForgotPasswordComponent implements OnInit {
  forgotForm: FormGroup;
  unSubscribe$ = new Subject();
  isLoading: boolean = false;

  constructor(
    private fb: FormBuilder,
    private toastr: ToastrService,
    private apiService: ApiService,
    private router: Router
  ) {
    this.forgotForm = this.fb.group({
      email: new FormControl('', [Validators.required, Validators.email])
    });
  }

  ngOnInit(): void {}

  forgotPasswordSubmit() {
    if (this.forgotForm.invalid) {
      this.forgotForm.markAllAsTouched();
      return;
    }
    this.isLoading = true;
    this.apiService.post(URLS.forgotPassword, this.forgotForm.value).pipe(takeUntil(this.unSubscribe$)).subscribe({
      next: (res: any) => {
        this.isLoading = false;
        if (res.status === "success") {
          this.toastr.success('Password reset link sent to your email');
          this.router.navigate(['/auth/signin']);
        } else {
          this.toastr.error(res.message || 'Failed to send reset link');
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
