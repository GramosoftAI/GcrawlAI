import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { AgentService, AgentStatusResponse } from 'src/app/services/agent.service';

@Component({
  selector: 'app-agent-result',
  templateUrl: './agent-result.component.html',
  styleUrls: ['./agent-result.component.scss']
})
export class AgentResultComponent implements OnInit, OnDestroy {
  status: AgentStatusResponse | null = null;
  private subs: Subscription[] = [];

  constructor(private agentService: AgentService) { }

  ngOnInit(): void {
    this.subs.push(
      this.agentService.status$.subscribe((status) => {
        this.status = status;
      })
    );
  }

  ngOnDestroy(): void {
    this.subs.forEach(sub => sub.unsubscribe());
  }

  formatJson(data: any): string {
    if (!data) {
      return '';
    }
    return JSON.stringify(data, null, 2);
  }
}
