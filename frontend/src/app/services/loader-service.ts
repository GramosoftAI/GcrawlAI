import { Injectable } from '@angular/core';
import { BehaviorSubject, Subject } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class LoaderService {
  showLoader = new Subject<boolean>();
  private counter = 0;

  constructor() {
  }

  show() {
    this.counter++;
    if (this.counter === 1) {
      this.showLoader.next(true);
    }
  }

  hide() {
    if (this.counter > 0) {
      this.counter--;
      if (this.counter === 0) {
        this.showLoader.next(false);
      }
    }
  }
}