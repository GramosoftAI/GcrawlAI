import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { ErrorPageComponent } from './modules/shared/component/error-page/error-page.component';

const routes: Routes = [
  { path: '', redirectTo: 'app', pathMatch: 'full' },

  {
    path: 'login',
    loadChildren: () =>
      import('./modules/auth/auth.module').then(m => m.AuthModule),
  },

  {
    path: 'app',
    loadChildren: () =>
      import('./modules/main/main.module').then(m => m.MainModule)
  },
  { path: '404_page', component: ErrorPageComponent },
  { path: '**', redirectTo: '404_page' },
];

@NgModule({
  imports: [RouterModule.forRoot(routes, {
    initialNavigation: 'enabledBlocking'
  })],
  exports: [RouterModule]
})
export class AppRoutingModule { }
