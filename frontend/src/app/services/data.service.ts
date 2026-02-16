import { Injectable } from "@angular/core";
import { LocalStorageService } from "./localstorage-service";
import { ActivatedRoute } from "@angular/router";

@Injectable({
    providedIn: 'root'
})

export class DataService {
    pageName: string = '';
    userData: any = this.localService.getUserDetails() || {} as any;
    userId: string = this.userData.user?.id || '';
    isActive: boolean = this.userData.user?.is_active === true;

    constructor(private localService: LocalStorageService, private activeRoute: ActivatedRoute) {
        if (this.localService.getAccessToken()) {
             this.setData();
        }
    }

    setData() {
        this.userData = this.localService.getUserDetails() || {} as any;
        this.userId = this.userData.user.user_id;
        this.isActive = this.userData.user.is_active === true;
    }

    // CLEAR SERVICE
    clear() {
        this.pageName = '';
        this.userData = {} as any;
        this.userId = '';
        this.isActive = false;
    }
}