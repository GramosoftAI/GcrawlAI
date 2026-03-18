import { Injectable } from '@angular/core';
import { webSocket, WebSocketSubject } from 'rxjs/webSocket';
import { timer, Observable, Subject } from 'rxjs';
import { retry, takeUntil } from 'rxjs/operators';
import { environment } from 'src/environement/environemet';
import { LocalStorageService } from './localstorage-service';

@Injectable({ providedIn: 'root' })
export class QuoteSocketService {
  private socket$!: WebSocketSubject<any>;
  private stop$ = new Subject<void>();

  constructor(private localService: LocalStorageService) { }

  connect(crawlId: string): Observable<any> {
    // Always close any existing socket before creating a new one
    this.close();
    // Reset stop$ so takeUntil works fresh each time
    this.stop$ = new Subject<void>();
    this.createSocket(crawlId);
    return this.socket$.pipe(
      takeUntil(this.stop$),
      retry({
        count: 5, // max 5 reconnect attempts on failure
        delay: (err, attempt) => {
          console.warn(`Socket reconnecting (attempt ${attempt})...`, err);
          return timer(3000);
        }
      })
    );
  }

  private createSocket(crawlId: string) {
    const token = this.localService.getAccessToken();
    const baseUrl = environment.wsUrl || 'wss://gcrawl.gramopro.ai';
    // Trying without trailing slash before query param
    const url = `${baseUrl}/ws/crawl/${crawlId}`;

    console.log('Attempting WebSocket connection to:', `${baseUrl}/ws/crawl/${crawlId}`);



    this.socket$ = webSocket({
      url: url,
      openObserver: {
        next: () => {
          console.log('WebSocket Connected:', crawlId);
          this.startPing();
        }
      },
      closeObserver: {
        next: () => {
          console.log('WebSocket Closed:', crawlId);
        }
      }
    });
  }

  private startPing() {
    timer(0, 20000).pipe(takeUntil(this.stop$)).subscribe(() => {
      if (this.socket$ && !this.socket$.closed) {
        this.socket$.next({ type: 'ping' });
      }
    });
  }

  send(data: any) {
    if (this.socket$ && !this.socket$.closed) {
      this.socket$.next(data);
    }
  }

  close() {
    this.stop$.next();
    this.stop$.complete();
    if (this.socket$) {
      this.socket$.complete();
      this.socket$ = null as any;
    }
  }
}
