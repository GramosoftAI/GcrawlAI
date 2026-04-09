import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { AgentService, AgentStatusResponse } from 'src/app/services/agent.service';

@Component({
  selector: 'app-agent-status',
  templateUrl: './agent-status.component.html',
  styleUrls: ['./agent-status.component.scss']
})
export class AgentStatusComponent implements OnInit, OnDestroy {
  jobIdInput = '';
  status: AgentStatusResponse | null = null;
  private subs: Subscription[] = [];

  constructor(private agentService: AgentService) { }

  ngOnInit(): void {
    this.subs.push(
      this.agentService.jobId$.subscribe((id) => {
        if (id) {
          this.jobIdInput = id;
        }
      })
    );
    this.subs.push(
      this.agentService.status$.subscribe((status) => {
        this.status = status;
      })
    );
  }

  ngOnDestroy(): void {
    this.subs.forEach(sub => sub.unsubscribe());
  }

  startTracking(): void {
    if (!this.jobIdInput) {
      return;
    }
    this.agentService.setJobId(this.jobIdInput);
    this.agentService.startPolling(this.jobIdInput);
  }

  cancelJob(): void {
    if (!this.jobIdInput) {
      return;
    }
    this.agentService.cancelJob(this.jobIdInput).subscribe(() => {
      this.agentService.startPolling(this.jobIdInput);
    });
  }
}
