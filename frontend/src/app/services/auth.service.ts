import { Injectable } from "@angular/core";
import { Router } from "@angular/router";
import { LocalStorageService } from "./localstorage-service";
import { MatDialog } from "@angular/material/dialog";
import { AlertComponent, AlertDialog } from "../modules/shared/component/alert/alert.component";
import { DataService } from "./data.service";

@Injectable({
  providedIn: 'root'
})

export class AuthService {
  isAuthenticated: boolean = this.localService.getAccessToken() ? true : false;

  constructor(private localService: LocalStorageService, private router: Router, private dataService: DataService, public dialog: MatDialog) { }

  login(data: any, value: any) {
    debugger
    this.localService.setAccessToken(data.access_token);
    this.localService.setUserDetails(data);
    this.dataService.setData();
    if (data.user?.is_active === true) {
      this.router.navigate(['/main'], {
        queryParams: {
          isLogin: value
        }
      });
    }
    else {
      this.router.navigate(['/404']);
    }

  }



  logout() {
    const message = 'Are you sure you want to logout';

    const dialogData = new AlertDialog("Logout", message);

    const dialogRef = this.dialog.open(AlertComponent, {
      maxWidth: "400px",
      data: dialogData
    });

    dialogRef.afterClosed().subscribe(dialogResult => {
      if (dialogResult) {
        const x = this.localService.getUserDetails()
        if (this.dataService.userData?.user) {
          this.router.navigate(['/auth'])
          this.localService.clearSessionStore();
          this.dataService.clear();
        }
        else {
          this.router.navigate(['/auth'])
          this.localService.clearSessionStore();
          this.dataService.clear();
        }
      }
    });
  }

  // isTokenExpired(token?: string): boolean {
  //   if (!token) token = this.localService.getAccessToken() || '{}';
  //   if (!token) return true;
  //   return false;
  // }

}
