import { Injectable } from '@angular/core';
import { BehaviorSubject, Subject } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class LoaderService {
  showLoader = new Subject<boolean>();

  constructor() {
  }

  show() {
    this.showLoader.next(true);
  }

  hide() {
    this.showLoader.next(false);
  }
}