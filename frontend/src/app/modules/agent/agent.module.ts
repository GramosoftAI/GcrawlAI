import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule } from '@angular/forms';

import { AgentRoutingModule } from './agent-routing.module';
import { AgentLayoutComponent } from './components/agent-layout/agent-layout.component';
import { AgentSubmitComponent } from './components/agent-submit/agent-submit.component';
import { AgentStatusComponent } from './components/agent-status/agent-status.component';
import { AgentResultComponent } from './components/agent-result/agent-result.component';
import { AgentCreditsComponent } from './components/agent-credits/agent-credits.component';
import { SharedModule } from '../shared/shared.module';

@NgModule({
  declarations: [
    AgentLayoutComponent,
    AgentSubmitComponent,
    AgentStatusComponent,
    AgentResultComponent,
    AgentCreditsComponent,
  ],
  imports: [
    CommonModule,
    ReactiveFormsModule,
    AgentRoutingModule,
    SharedModule,
  ]
})
export class AgentModule { }
