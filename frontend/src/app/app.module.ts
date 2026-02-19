import { CUSTOM_ELEMENTS_SCHEMA, NgModule } from '@angular/core';
import { BrowserModule, provideClientHydration } from '@angular/platform-browser';
import { AppRoutingModule } from './app-routing.module';
import { AppComponent } from './app.component';
import { ContainerComponent } from './container/container.component';
import { FormsModule } from '@angular/forms';
import { httpInterceptorProviders } from './interceptors';
import { HttpClientModule } from '@angular/common/http';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { ToastrModule } from 'ngx-toastr';
import * as $ from 'jquery';
import { MatDialogModule } from '@angular/material/dialog';
import { CommonModule } from '@angular/common';
import { SharedModule } from "./modules/shared/shared.module";

@NgModule({
  declarations: [
    AppComponent,
    ContainerComponent
  ],
  imports: [
    BrowserModule,
    AppRoutingModule,
    FormsModule,
    MatDialogModule,
    BrowserAnimationsModule,
    HttpClientModule,
    CommonModule,
    ToastrModule.forRoot({
        timeOut: 5000, // Toast will be shown for 5 seconds
        positionClass: 'toast-top-right', // Position of the toast
        preventDuplicates: true,
    }),
    SharedModule
],
  providers: [httpInterceptorProviders, provideClientHydration()],
  schemas: [CUSTOM_ELEMENTS_SCHEMA],
  bootstrap: [AppComponent]
})
export class AppModule { }
