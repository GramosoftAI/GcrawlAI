import { CurrencyPipe, DatePipe } from "@angular/common";
import { Injectable } from "@angular/core";
import { MatDialog } from "@angular/material/dialog";
import { DataService } from "./data.service";
import { FormControl, FormGroup } from "@angular/forms";

@Injectable({
    providedIn: 'root'
})

export class DependencyService {
    constructor(public dialog: MatDialog) {
    }

    getFormControl(formGroup: FormGroup, str: string): FormControl<any> {
        return formGroup.get(str) as FormControl<any>
    }

    getFormData(file: File) {
        const formData = new FormData();
        formData.append('image', file);
    }

    goBack(): void {
        window.history.back();
    }
}