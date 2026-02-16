import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { SigninComponent } from './component/signin/signin.component';

const routes: Routes = [
  { path: '', component: SigninComponent,
    children: [
      {
      path: '',
      redirectTo: "",
      pathMatch: 'full'
      },
      {
        path: 'signin',
        component: SigninComponent
      }
    ]
   }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AuthRoutingModule { }
