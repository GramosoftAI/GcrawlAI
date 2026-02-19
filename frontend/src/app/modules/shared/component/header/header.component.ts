import { Component, computed } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from 'src/app/services/auth.service';
import { LocalStorageService } from 'src/app/services/localstorage-service';
import { ThemeService } from 'src/app/services/theme.service';

@Component({
  selector: 'app-header',
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.scss']
})
export class HeaderComponent {
  userDetails: any;
  token: any;
  isDarkTheme = computed(() => this.themeService.currentTheme() === 'dark');

  constructor(private authService: AuthService, private localService: LocalStorageService, private router: Router, public themeService: ThemeService) { }

  ngOnInit() {
    this.token = this.localService.getAccessToken()
    this.userDetails = this.localService.getUserDetails();
    console.log('userDetails', this.userDetails)
    console.log('token', this.token)
  }

  Onclick() {
    if (!this.token) {
      this.router.navigate(['/auth'])
    }
  }

  logout() {
  this.authService.logout();
  this.token = false;
  this.router.navigate(['/login']);
}

}
