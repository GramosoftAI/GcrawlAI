import { HttpEvent, HttpHandler, HttpHeaders, HttpInterceptor, HttpRequest, HttpResponse } from "@angular/common/http";
import { Injectable } from "@angular/core";
import { ERROR_ENUM } from "../enums/error.enum";
import { catchError, map, Observable, throwError } from "rxjs";
import { AuthService } from "../services/auth.service";
import { LocalStorageService } from "../services/localstorage-service";
import { LoaderService } from "../services/loader-service";
import { ToastrService } from "ngx-toastr";
import { MatDialog } from "@angular/material/dialog";
import { AlertComponent, AlertDialog } from "../modules/shared/component/alert/alert.component";
import { environment } from "../../environement/environemet";

@Injectable()

export class AuthInterceptor implements HttpInterceptor {
    errEnum: any = ERROR_ENUM;

    constructor(public authService: AuthService, private loaderService: LoaderService, private localService: LocalStorageService, private toastr: ToastrService, public dialog: MatDialog,) { }
    intercept(req: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
        if (req.url.includes('login')) {
            if (!req.headers.has('Content-Type')) {
                req = req.clone({
                    headers: req.headers.set('Content-Type', 'application/json')
                });
            }
        }
        else if (req.url.startsWith(environment.apiUrl)) {
            const token = this.localService.getAccessToken();
            if (token) {
                const type = req.headers.get('Type');
                const isNoToStopLoader = req.headers.get('NoToStopLoader');
                req = req.clone({
                    headers: new HttpHeaders({
                        // 'Content-Type': 'application/json',
                        // 'Content-Type': 'multipart/form-data',
                        // "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Headers": "X-Requested-With",
                        "Access-Control-Allow-Methods": "GET, POST, DELETE, PUT , OPTIONS",
                        "Authorization": `${token}`,
                        "Type": `${type ? type : 'NT'}`,
                        "NoToStopLoader": `${isNoToStopLoader}`

                    })
                });
            }
        }

        return next.handle(req).pipe(
            map((event: HttpEvent<any>) => {
                if (event instanceof HttpResponse) {
                    if (event.url && !event.url.includes('assets/data') && event.body) {
                        // NT = No Interceptor handling — skip all toasts and dialogs
                        if (req.headers.get('Type') === 'NT') {
                            return event;
                        }
                        else {
                            if (event.status !== 200) {
                                const message = event.body?.message || 'Something went wrong';
                                const dialogData = new AlertDialog("Alert", message, 'AL');
                                this.dialog.open(AlertComponent, {
                                    maxWidth: "400px",
                                    data: dialogData
                                });
                            } else {
                                if (event.body?.message) {
                                    this.toastr.info(event.body.message);
                                }
                            }
                        }
                    }
                }
                return event;
            })
            , catchError((err: any) => {
                this.loaderService.hide();
                if (err.error && err.error.message) {
                    this.toastr.error(err.error.message);
                } else if (err.message) {
                    this.toastr.error(err.message);
                } else {
                    this.toastr.error('An unexpected error occurred');
                }
                return throwError(err);
            })
        );
    }

}