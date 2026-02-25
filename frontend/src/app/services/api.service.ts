import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environement/environemet';

@Injectable({
    providedIn: 'root'
})
export class ApiService {

    constructor(private http: HttpClient) { }

    get(url: string, params?: any, suppressLoader: boolean = true): Observable<any> {
        const headers = (suppressLoader && url.startsWith(environment.apiUrl))
            ? new HttpHeaders().set('NoToStopLoader', 'TRUE')
            : undefined;
        return this.http.get(`${url}`, { params, headers });
    }

    // NT for No toastr, CR for create, ED for edit, DL for delete, CL for cancel, UP for upload, SE for Send, OR for order reject, OC for order complete, OS for order reschedule, LO for Login

    post(url: string, data: any, tost?: { type: 'NT' | 'CR' | 'ED' | 'DL' | 'CL' | 'UP' | 'SE' | 'OC' | 'OR' | 'OS' | 'LO'; name?: string; }, p0?: string): Observable<any> {
        let headers = new HttpHeaders().set('Type', tost ? tost.type : 'NT');
        if (url.startsWith(environment.apiUrl)) {
            headers = headers.set('NoToStopLoader', 'TRUE');
        }
        return this.http.post(`${url}`, data, { headers: headers });
    }

    patch(url: string, data: any, tost?: { type: 'NT' | 'CR' | 'ED' | 'DL' | 'CL' | 'UP' | 'SE', name?: string }): Observable<any> {
        let headers = new HttpHeaders().set('Type', tost ? tost.type : 'NT');
        if (url.startsWith(environment.apiUrl)) {
            headers = headers.set('NoToStopLoader', 'TRUE');
        }
        return this.http.patch(`${url}`, data, { headers: headers });
    }

    delete(url: string, params?: any): Observable<any> {
        let headers = new HttpHeaders();
        if (url.startsWith(environment.apiUrl)) {
            headers = headers.set('NoToStopLoader', 'TRUE');
        }
        return this.http.delete(`${url}`, { params, headers });
    }
}
