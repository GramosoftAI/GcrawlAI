import { Injectable, signal, effect, Inject, PLATFORM_ID, DestroyRef, inject } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';

@Injectable({
  providedIn: 'root'
})
export class ThemeService {
  readonly currentTheme = signal<'light' | 'dark'>('light');

  constructor(@Inject(PLATFORM_ID) private platformId: Object) {
    if (isPlatformBrowser(this.platformId)) {
      const theme = this.getInitialTheme();
      this.currentTheme.set(theme);
    }

    // effect() is valid here — constructor IS injection context
    effect(() => {
      const theme = this.currentTheme();

      if (isPlatformBrowser(this.platformId)) {
        localStorage.setItem('theme', theme);

        const body = document.body;
        body.classList.remove('dark-theme', 'light-theme');
        body.classList.add(theme === 'dark' ? 'dark-theme' : 'light-theme');
      }
    });
  }

  toggleTheme() {
    // Remove the debugger statement — it pauses execution in DevTools
    this.currentTheme.update(theme => theme === 'light' ? 'dark' : 'light');
  }

  private getInitialTheme(): 'light' | 'dark' {
    if (!isPlatformBrowser(this.platformId)) {
      return 'light';
    }
    const savedTheme = localStorage.getItem('theme') as 'light' | 'dark' | null;
    if (savedTheme === 'light' || savedTheme === 'dark') {
      return savedTheme;
    }
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
}