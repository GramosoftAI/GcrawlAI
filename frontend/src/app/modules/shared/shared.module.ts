import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { SharedRoutingModule } from './shared-routing.module';
import { HeaderComponent } from './component/header/header.component';
import { FooterComponent } from './component/footer/footer.component';
import { MatDialogModule } from '@angular/material/dialog';
import { OtpModalComponent } from './component/otp-modal/otp-modal.component';
import { NgOtpInputModule } from 'ng-otp-input';
import { TimerPipe } from 'src/app/pipes/timer.pipe';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { AlertComponent } from './component/alert/alert.component';
import { ErrorPageComponent } from './component/error-page/error-page.component';
import { LoaderComponent } from './component/loader/loader.component';
import { ToastrModule } from 'ngx-toastr';
import { AnimatebgComponent } from './component/animatebg/animatebg.component';

@NgModule({
  declarations: [
    HeaderComponent,
    FooterComponent,
    OtpModalComponent,
    AlertComponent,
    TimerPipe,
    ErrorPageComponent,
    LoaderComponent,
    AnimatebgComponent,
  ],
  imports: [
    ReactiveFormsModule,
    FormsModule,
    CommonModule,
    SharedRoutingModule,
    MatDialogModule,
    NgOtpInputModule,
    MatIconModule,
    MatInputModule,
    ToastrModule.forRoot({
      preventDuplicates: true,
      timeOut: 3000
    })
  ],
  exports: [
    AnimatebgComponent,
    HeaderComponent,
    FooterComponent,
    OtpModalComponent,
    LoaderComponent,
    MatDialogModule,
    NgOtpInputModule,
    ReactiveFormsModule,
    FormsModule,
    MatIconModule,
    MatInputModule
  ]
})
export class SharedModule { }
