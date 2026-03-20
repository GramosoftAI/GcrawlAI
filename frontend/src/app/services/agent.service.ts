import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable, Subscription, interval, switchMap } from 'rxjs';
import { ApiService } from './api.service';
import { environment } from '../../environement/environemet';

export interface AgentRequestPayload {
  prompt: string;
  urls?: string[];
  schema?: any;
  strictConstrainToURLs?: boolean;
  model?: string;
  maxCredits?: number;
}

export interface AgentStartResponse {
  success: boolean;
  id: string;
}

export interface AgentStatusResponse {
  success: boolean;
  status: 'processing' | 'completed' | 'failed' | 'cancelled';
  data?: any;
  creditsUsed: number;
  expiresAt?: string;
  model?: string;
  error?: string;
}

@Injectable({
  providedIn: 'root'
})
export class AgentService {
  private jobIdSubject = new BehaviorSubject<string | null>(null);
  private statusSubject = new BehaviorSubject<AgentStatusResponse | null>(null);
  private maxCreditsSubject = new BehaviorSubject<number | null>(null);
  private pollingSub?: Subscription;

  jobId$ = this.jobIdSubject.asObservable();
  status$ = this.statusSubject.asObservable();
  maxCredits$ = this.maxCreditsSubject.asObservable();

  constructor(private api: ApiService) { }

  startJob(payload: AgentRequestPayload): Observable<AgentStartResponse> {
    const url = `${environment.apiUrl}/v1/agent`;
    return this.api.post(url, payload);
  }

  setJobId(jobId: string, maxCredits?: number): void {
    this.jobIdSubject.next(jobId);
    if (maxCredits) {
      this.maxCreditsSubject.next(maxCredits);
    }
  }

  fetchStatus(jobId: string): Observable<AgentStatusResponse> {
    const url = `${environment.apiUrl}/v1/agent/${jobId}`;
    return this.api.get(url);
  }

  startPolling(jobId: string): void {
    this.stopPolling();
    this.pollingSub = interval(3000)
      .pipe(switchMap(() => this.fetchStatus(jobId)))
      .subscribe({
        next: (status) => {
          this.statusSubject.next(status);
          if (['completed', 'failed', 'cancelled'].includes(status.status)) {
            this.stopPolling();
          }
        },
        error: () => {
          this.stopPolling();
        }
      });
  }

  stopPolling(): void {
    if (this.pollingSub) {
      this.pollingSub.unsubscribe();
      this.pollingSub = undefined;
    }
  }

  cancelJob(jobId: string): Observable<any> {
    const url = `${environment.apiUrl}/v1/agent/${jobId}`;
    return this.api.delete(url);
  }

  clear(): void {
    this.jobIdSubject.next(null);
    this.statusSubject.next(null);
    this.maxCreditsSubject.next(null);
    this.stopPolling();
  }
}
