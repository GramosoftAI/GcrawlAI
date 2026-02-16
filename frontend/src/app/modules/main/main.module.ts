import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { MainRoutingModule } from './main-routing.module';
import { HomeComponent } from './component/home/home.component';
import { HomesearchtabComponent } from './component/homesearchtab/homesearchtab.component';
import { HomesearchresultComponent } from './component/homesearchresult/homesearchresult.component';
import { SharedModule } from "src/app/modules/shared/shared.module";
import { ReportPageComponent } from './component/report-page/report-page.component';


@NgModule({
  declarations: [
    HomeComponent,
    HomesearchtabComponent,
    HomesearchresultComponent,
    ReportPageComponent
  ],
  imports: [
    CommonModule,
    MainRoutingModule,
    SharedModule
]
})
export class MainModule { }
