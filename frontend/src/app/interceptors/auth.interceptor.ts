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
        else {
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
                        if (event.body.status === true) {
                            if (req.method == 'DELETE') {
                                this.toastr.success('Deleted Successfully...');
                            } else {
                                switch (req.headers.get('Type')) {
                                    case 'CR':
                                        this.toastr.success('Created Successfully...');
                                        break;

                                    case 'UP':
                                        this.toastr.success('Uploaded Successfully...');
                                        break;

                                    case 'ED':
                                        this.toastr.success('Updated Successfully...');
                                        break;

                                    case 'DL':
                                        this.toastr.success('Deleted Successfully...');
                                        break;

                                    case 'CL':
                                        this.toastr.success('Canceled Successfully...');
                                        break;

                                    case 'SE':
                                        this.toastr.success('Sented Successfully...');
                                        break;

                                    case 'OC':
                                        this.toastr.success('Order Completed Successfully...');
                                        break;

                                    case 'OR':
                                        this.toastr.success('Order Rejected Successfully...');
                                        break;

                                    case 'OS':
                                        this.toastr.success('Order Rescheduled Successfully...');
                                        break;

                                    case 'LO':
                                        this.toastr.success('Login Successfully......');
                                        break;

                                    default:
                                        break;
                                }
                            }
                        }
                        else {
                            if (event.status !== 200) {
                                const message = event.status !== 200 ? event.body?.message : 'Some thing went wrong';
                                const dialogData = new AlertDialog("Alert", message, 'AL');
                                const dialogRef = this.dialog.open(AlertComponent, {
                                    maxWidth: "400px",
                                    data: dialogData
                                });
                            } else {
                                const message = event.status !== 200 ? event.body?.message : 'Some thing went wrong';
                                if (event.status !== 200) {
                                    this.toastr.info(message);
                                }
                            }
                        }

                    }
                }
                return event;
            })
            , catchError((err: any) => {
                this.loaderService.hide();
                return throwError(err);
            })
        );
    }

}