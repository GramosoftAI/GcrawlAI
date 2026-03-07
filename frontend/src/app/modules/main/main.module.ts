import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule } from '@angular/forms';

import { MainRoutingModule } from './main-routing.module';
import { HomeComponent } from './component/home/home.component';
import { HomesearchtabComponent } from './component/homesearchtab/homesearchtab.component';
import { HomesearchresultComponent } from './component/homesearchresult/homesearchresult.component';
import { SharedModule } from "src/app/modules/shared/shared.module";
import { ReportPageComponent } from './component/report-page/report-page.component';
import { CrawlHistoryComponent } from './component/crawl-history/crawl-history.component';
import { ContactUsComponent } from './component/contact-us/contact-us.component';
import { CarouselModule } from 'ngx-owl-carousel-o';


@NgModule({
  declarations: [
    HomeComponent,
    HomesearchtabComponent,
    HomesearchresultComponent,
    ReportPageComponent,
    CrawlHistoryComponent,
    ContactUsComponent
  ],
  imports: [
    CommonModule,
    MainRoutingModule,
    SharedModule,
    ReactiveFormsModule,
    CarouselModule
  ]
})
export class MainModule { }
