import { Injectable } from "@angular/core";
import {
    HttpEvent,
    HttpRequest,
    HttpHandler,
    HttpInterceptor,
    HttpResponse
} from "@angular/common/http";
import { Observable } from "rxjs";
import { finalize, delay, map } from "rxjs/operators";
import { LoaderService } from "../services/loader-service";

@Injectable()
export class LoaderInterceptor implements HttpInterceptor {
    constructor(private loaderService: LoaderService) {
    }
    intercept(
        req: HttpRequest<any>,
        next: HttpHandler
    ): Observable<HttpEvent<any>> {

        this.loaderService.show();

        return next.handle(req).pipe(
            delay(500),
            finalize(() => {
                if (req.headers.get('NoToStopLoader') !== 'TRUE') {
                    this.loaderService.hide();
                }
            }),
            map((event: HttpEvent<any>) => {
                if (event instanceof HttpResponse) {
                    if (event.body.status !== true && req.headers.get('NoToStopLoader') == 'TRUE') {
                        this.loaderService.hide();
                    }
                }
                // Your logic here for manipulating the response, if needed
                return event;
            }))
    }
}
