import { Component, OnInit, OnDestroy } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { ApiService } from 'src/app/services/api.service';
import { ToastrService } from 'ngx-toastr';
import { URLS } from 'src/app/configs/api.config';
import { Subject, takeUntil } from 'rxjs';
import { CountryISO, SearchCountryField } from 'ngx-intl-tel-input';

@Component({
  selector: 'app-contact-us',
  templateUrl: './contact-us.component.html',
  styleUrls: ['./contact-us.component.scss']
})
export class ContactUsComponent implements OnInit, OnDestroy {
  contactForm: FormGroup;
  isSubmitting = false;
  unSubscribe$ = new Subject<void>();
  separateDialCode = true;
  selectedCountryISO: any = CountryISO.India;
  SearchCountryField = SearchCountryField;
  CountryISO = CountryISO;
  preferredCountries: CountryISO[] = [CountryISO.India, CountryISO.UnitedStates, CountryISO.UnitedKingdom];

  constructor(private fb: FormBuilder, private apiService: ApiService, private toastr: ToastrService) {
    this.contactForm = this.fb.group({
      name: ['', [Validators.required, Validators.minLength(2)]],
      email: ['', [Validators.required, Validators.email]],
      mobile: ['', [Validators.required]],
      company: ['', [Validators.required]],
      country: ['India'],
      message: ['', [Validators.required, Validators.minLength(10)]]
    });
  }

  ngOnInit(): void {
    setTimeout(() => {
      if (!this.contactForm.get('country')?.value) {
        this.contactForm.patchValue({ country: 'India' }, { emitEvent: false });
      }
    }, 100);
    this.contactForm.get('country')?.disable()
  }

  onCountryChange(event: any) {
    if (event && event.name) {
      this.contactForm.patchValue({
        country: event.name
      }, { emitEvent: false });
    }
  }

  get f() { return this.contactForm.controls; }

  isInvalid(field: string): boolean {
    const ctrl = this.contactForm.get(field);
    return !!(ctrl && ctrl.invalid && (ctrl.touched || this.isSubmitting));
  }

  submitContact() {
    if (this.contactForm.invalid) {
      this.contactForm.markAllAsTouched();
      return;
    }
    this.isSubmitting = true;
    const payload = { ...this.contactForm.getRawValue() };

    // Extract the phone number from the ngx-intl-tel-input object
    if (payload.mobile && typeof payload.mobile === 'object') {
      payload.mobile = payload.mobile.e164Number || payload.mobile.number || payload.mobile;
    }
    this.apiService.post(URLS.contact, payload, { type: 'NT' }).pipe(takeUntil(this.unSubscribe$)).subscribe({
      next: (res: any) => {
        this.isSubmitting = false;
        if (res.status === 'success') {
          this.toastr.success(res.message || 'Message sent successfully!');
          this.contactForm.reset();
        } else {
          this.toastr.error(res.message || 'Failed to send message.');
        }
      },
      error: () => {
        this.isSubmitting = false;
        this.toastr.error('Something went wrong. Please try again.');
      }
    });
  }

  ngOnDestroy(): void {
    this.unSubscribe$.next();
    this.unSubscribe$.complete();
  }
}
