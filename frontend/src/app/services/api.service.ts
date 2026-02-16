import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
    providedIn: 'root'
})
export class ApiService {

    constructor(private http: HttpClient) { }

    get(url: string, params?: any): Observable<any> {
        return this.http.get(`${url}`, { params: params });
    }

    // NT for No toastr, CR for create, ED for edit, DL for delete, CL for cancel, UP for upload, SE for Send, OR for order reject, OC for order complete, OS for order reschedule, LO for Login

    post(url: string, data: any, tost?: { type: 'NT' | 'CR' | 'ED' | 'DL' | 'CL' | 'UP' | 'SE' | 'OC' | 'OR' | 'OS' | 'LO', name?: string }, NoToStopLoader?: 'TRUE' | 'FALSE'): Observable<any> {
        const headers = new HttpHeaders().set('Type', tost ? tost.type : 'NT').set('NoToStopLoader', NoToStopLoader ? NoToStopLoader : 'FALSE');
        return this.http.post(`${url}`, data, { headers: headers });
    }

    patch(url: string, data: any, tost?: { type: 'NT' | 'CR' | 'ED' | 'DL' | 'CL' | 'UP' | 'SE', name?: string }): Observable<any> {
        const headers = new HttpHeaders().set('Type', tost ? tost.type : 'NT');
        return this.http.patch(`${url}`, data, { headers: headers });
    }

    delete(url: string, params?: any): Observable<any> {
        return this.http.delete(`${url}`, { params: params });
    }
}
