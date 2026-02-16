import { Injectable } from '@angular/core';
import { CanActivate, ActivatedRouteSnapshot, RouterStateSnapshot, UrlTree, Router } from '@angular/router';
import { Observable } from 'rxjs';
import { DataService } from './data.service';
import { LocalStorageService } from './localstorage-service';
import { environment } from 'src/environement/environemet';

@Injectable({
  providedIn: 'root'
})
export class AuthGuard implements CanActivate {

  constructor(
    private router: Router,
    private dataService: DataService,
    private localService: LocalStorageService
  ) {}

  canActivate( next: ActivatedRouteSnapshot, state: RouterStateSnapshot ): Observable<boolean | UrlTree> | Promise<boolean | UrlTree> | boolean | UrlTree {
    if (!this.dataService.userId) {
      this.router.navigate(['/auth']);
      return false;
    }
    const userType = this.dataService.userData;
    if (userType.access_token) {
      return true;
    } else if (!userType.access_token) {
      this.router.navigate(['/404']);
      return false;
    }

    return true;
  }
}
