import { AbstractControl, FormGroup, ValidatorFn } from "@angular/forms";

export function passwordValidator(): ValidatorFn {
  const pattern = /^(?=.*\d)(?=.*[!@#$%^&*])(?=.*[a-z])(?=.*[A-Z]).{8,}$/;
  // Validators.pattern("(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9])(?=.*[#$@$!%*?&])[A-Za-z\d#$@$!%*?&].{7,}")

  return (control: AbstractControl): { [key: string]: any } | null => {
    const value = control.value;

    if (value && !pattern.test(value)) {
      return { 'passwordValidator': true };
    }

    return null;
  };
}

export function ConfirmPasswordValidator(controlName: string, matchingControlName: string) {
  return (formGroup: FormGroup) => {
    const control = formGroup.controls[controlName];
    const matchingControl = formGroup.controls[matchingControlName];

    if (control.value !== matchingControl.value) {
      matchingControl.setErrors({ confirmPasswordValidator: true });
    } else {
      matchingControl.setErrors(null);
    }
  };
}