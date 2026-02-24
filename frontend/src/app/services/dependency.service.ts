import { Injectable, Inject, PLATFORM_ID } from "@angular/core";
import { isPlatformBrowser } from "@angular/common";
import { MatDialog } from "@angular/material/dialog";
import { FormControl, FormGroup } from "@angular/forms";

@Injectable({
  providedIn: 'root'
})
export class DependencyService {

  private isBrowser: boolean;

  constructor(
    public dialog: MatDialog,
    @Inject(PLATFORM_ID) private platformId: Object
  ) {
    this.isBrowser = isPlatformBrowser(this.platformId);
  }

  getFormControl(formGroup: FormGroup, str: string): FormControl<any> {
    return formGroup.get(str) as FormControl<any>;
  }

  getFormData(file: File): FormData {
    const formData = new FormData();
    formData.append('image', file);
    return formData;
  }

  goBack(): void {
    if (this.isBrowser) {
      window.history.back();
    }
  }
}
