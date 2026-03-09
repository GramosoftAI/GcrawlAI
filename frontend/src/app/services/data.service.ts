import { Inject, Injectable, PLATFORM_ID, signal } from "@angular/core";
import { LocalStorageService } from "./localstorage-service";
import { ActivatedRoute } from "@angular/router";
import { isPlatformBrowser } from "@angular/common";

@Injectable({
    providedIn: 'root'
})

export class DataService {
    pageName: string = '';
    // Signals for reactive state
    userData = signal<any>({});
    userId = signal<string>('');
    isActive = signal<boolean>(false);

    constructor(
        private localService: LocalStorageService,
        private activeRoute: ActivatedRoute,
        @Inject(PLATFORM_ID) private platformId: Object
    ) {
        if (isPlatformBrowser(this.platformId)) {
            if (this.localService.getAccessToken()) {
                this.setData();
            }
        }
    }

    setData() {
        if (isPlatformBrowser(this.platformId)) {
            const data = this.localService.getUserDetails() || {};
            this.userData.set(data);
            this.userId.set(data?.user?.user_id || data?.user?.id || '');
            this.isActive.set(data?.user?.is_active === true);
        }
    }

    // CLEAR SERVICE
    clear() {
        this.pageName = '';
        this.userData.set({});
        this.userId.set('');
        this.isActive.set(false);
    }
}