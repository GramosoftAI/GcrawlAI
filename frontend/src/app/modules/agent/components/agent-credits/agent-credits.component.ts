import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { AgentService, AgentStatusResponse } from 'src/app/services/agent.service';

@Component({
  selector: 'app-agent-credits',
  templateUrl: './agent-credits.component.html',
  styleUrls: ['./agent-credits.component.scss']
})
export class AgentCreditsComponent implements OnInit, OnDestroy {
  creditsUsed = 0;
  maxCredits: number | null = null;
  private subs: Subscription[] = [];

  constructor(private agentService: AgentService) { }

  ngOnInit(): void {
    this.subs.push(
      this.agentService.status$.subscribe((status: AgentStatusResponse | null) => {
        this.creditsUsed = status?.creditsUsed || 0;
      })
    );
    this.subs.push(
      this.agentService.maxCredits$.subscribe((value) => {
        this.maxCredits = value;
      })
    );
  }

  ngOnDestroy(): void {
    this.subs.forEach(sub => sub.unsubscribe());
  }

  get usagePercent(): number {
    if (!this.maxCredits) {
      return 0;
    }
    return Math.min(100, Math.round((this.creditsUsed / this.maxCredits) * 100));
  }
}
