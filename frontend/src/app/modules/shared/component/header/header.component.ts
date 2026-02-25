import { isPlatformBrowser } from '@angular/common';
import { Component, computed, Inject, PLATFORM_ID } from '@angular/core';
import { Router } from '@angular/router';
import { ApiService } from 'src/app/services/api.service';
import { AuthService } from 'src/app/services/auth.service';
import { GithubService } from 'src/app/services/github.service';
import { LocalStorageService } from 'src/app/services/localstorage-service';
import { ThemeService } from 'src/app/services/theme.service';

@Component({
  selector: 'app-header',
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.scss']
})
export class HeaderComponent {
  userDetails: any;
  stars: number = 0;
  token: any;
  isDarkTheme = computed(() => this.themeService.currentTheme() === 'dark');

  constructor(@Inject(PLATFORM_ID) private platformId: Object, private authService: AuthService, private github: GithubService, private localService: LocalStorageService, private router: Router, public themeService: ThemeService) { }

  ngOnInit(): void {
    if (isPlatformBrowser(this.platformId)) {
      this.token = this.localService.getAccessToken();
      this.userDetails = this.localService.getUserDetails();
      this.loadGithubStars();
    }

  }

  private loadGithubStars(): void {
    this.github.getStars().subscribe({
      next: (res) => {
        this.stars = res?.stargazers_count ?? 0;
      },
      error: (err) => {
        console.error('GitHub API Error:', err);
        this.stars = 0;
      }
    });
  }


  Onclick() {
    if (!this.token) {
      this.router.navigate(['/auth'])
    }
  }

  logout() {
    this.authService.logout();
  }

}
