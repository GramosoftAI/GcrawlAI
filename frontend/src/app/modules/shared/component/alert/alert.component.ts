import { AfterViewInit, Component, Inject, OnInit, Renderer2 } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

@Component({
  selector: 'app-alert',
  templateUrl: './alert.component.html',
  styleUrls: ['./alert.component.scss']
})
export class AlertComponent implements OnInit, AfterViewInit {
  title: string;
  message: string;
  type?: string;
  pwdData?: { id?: string, pwd: string};
  isClick: boolean = false;

  constructor(public dialogRef: MatDialogRef<AlertComponent>, @Inject(MAT_DIALOG_DATA) public data: AlertDialog,private renderer: Renderer2) {
    this.title = data.title;
    this.message = data.message;
    this.type = data.type;
    this.pwdData = data.data;
  }

  ngOnInit(): void {
  }

  onConfirm(): void {
    this.dialogRef.close(this.type != 'AL');
  }

  onDismiss(): void {
    this.dialogRef.close(false);
  }

  copyText(): string{
    return `User Name: ${this.pwdData?.id}\n\nPassword: ${this.pwdData?.pwd}`
  }

  ngAfterViewInit(): void {
    // Accessing the cdk-overlay-container and adding a class to it
    const overlayContainer = document.getElementsByClassName('cdk-overlay-container')[0];
    this.renderer.addClass(overlayContainer, 'overlay-index');
  }
}

export class AlertDialog {
  constructor(public title: string, public message: string, public type?: string, public data?: { id?: string, pwd: string}) {
  }
}