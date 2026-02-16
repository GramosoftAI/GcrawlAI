import { Injectable } from '@angular/core';
import { webSocket, WebSocketSubject } from 'rxjs/webSocket';
import { timer, Observable, Subject } from 'rxjs';
import { retryWhen, delayWhen, tap, takeUntil } from 'rxjs/operators';

@Injectable({ providedIn: 'root' })
export class QuoteSocketService {
  private socket$!: WebSocketSubject<any>
  private stop$ = new Subject<void>();
  private currentId: string | null = null;

  connect(crawlId: string): Observable<any> {
    this.currentId = crawlId;
    if (!this.socket$ || this.socket$.closed) {
      this.createSocket(crawlId);
    }
    return this.socket$.pipe(takeUntil(this.stop$),
        // Auto reconnect
        retryWhen(err =>
          err.pipe(
            tap(() => console.log('Socket Reconnecting...')),
            delayWhen(() => timer(3000))
          )
        )
      );
  }


  private createSocket(crawlId: string) {
    this.socket$ = webSocket({
      url: `ws://192.168.1.9:8000/ws/crawl/${crawlId}`,
      openObserver: {
        next: () => {
          console.log('WebSocket Connected');
          this.startPing(); // keep alive
        }
      },
      closeObserver: {
        next: () => {
          console.log('WebSocket Closed');
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
    if (this.socket$) {
      this.socket$.complete();
      this.socket$ = null as any;
    }
  }
}
