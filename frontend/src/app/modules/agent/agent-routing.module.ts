import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { AgentLayoutComponent } from './components/agent-layout/agent-layout.component';
import { AgentSubmitComponent } from './components/agent-submit/agent-submit.component';
import { AgentStatusComponent } from './components/agent-status/agent-status.component';
import { AgentResultComponent } from './components/agent-result/agent-result.component';
import { AgentCreditsComponent } from './components/agent-credits/agent-credits.component';

const routes: Routes = [
  {
    path: '',
    component: AgentLayoutComponent,
    children: [
      { path: '', redirectTo: 'submit', pathMatch: 'full' },
      { path: 'submit', component: AgentSubmitComponent },
      { path: 'status', component: AgentStatusComponent },
      { path: 'result', component: AgentResultComponent },
      { path: 'credits', component: AgentCreditsComponent },
    ]
  }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class AgentRoutingModule { }
