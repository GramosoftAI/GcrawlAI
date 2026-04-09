import { Inject, Injectable, PLATFORM_ID, signal } from "@angular/core";
import { Router } from "@angular/router";
import { LocalStorageService } from "./localstorage-service";
import { MatDialog } from "@angular/material/dialog";
import { AlertComponent, AlertDialog } from "../modules/shared/component/alert/alert.component";
import { DataService } from "./data.service";
import { isPlatformBrowser } from "@angular/common";

@Injectable({
  providedIn: 'root'
})

export class AuthService {
  // Signals for reactive state
  public isLoggedIn = signal<boolean>(false);
  public currentUser = signal<any>(null);

  constructor(
    private localService: LocalStorageService,
    private router: Router,
    private dataService: DataService,
    public dialog: MatDialog,
    @Inject(PLATFORM_ID) private platformId: Object
  ) {
    if (isPlatformBrowser(this.platformId)) {
      this.syncState();
    }
  }

  private syncState() {
    const token = this.localService.getAccessToken();
    const user = this.localService.getUserDetails();
    this.isLoggedIn.set(!!token);
    this.currentUser.set(user);
  }

  login(data: any) {
    this.localService.setAccessToken(data.access_token);
    this.localService.setUserDetails(data);
    this.dataService.setData();

    // Update signals
    this.isLoggedIn.set(true);
    this.currentUser.set(data);

    if (data.user?.is_active === true) {
      if (isPlatformBrowser(this.platformId) && window.location.hostname !== 'localhost') {
        window.location.href = '/app';
      } else {
        this.router.navigate(['/app']);
      }
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
        this.localService.clearSessionStore();
        this.dataService.clear();

        // Update signals
        this.isLoggedIn.set(false);
        this.currentUser.set(null);

        this.router.navigate(['/login']);
      }
    });
  }
}
