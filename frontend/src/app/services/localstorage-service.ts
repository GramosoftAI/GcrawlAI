import { Injectable } from '@angular/core';
import { environment } from 'src/environement/environemet';
import * as CryptoJS from 'crypto-js';

@Injectable({
  providedIn: 'root'
})
export class LocalStorageService {
  private secretKey: string = environment.secretKey;

  constructor() { }

  private encrypt(data: any): string {
    try {
      const jsonData = JSON.stringify(data);
      const encrypted = CryptoJS.AES.encrypt(jsonData, this.secretKey).toString();
      return encrypted;
    } catch (e) {
      return '';
    }
  }

  private decrypt(data: string): any {
    try {
      const bytes = CryptoJS.AES.decrypt(data, this.secretKey);
      const decryptedText = bytes.toString(CryptoJS.enc.Utf8);
      if (!decryptedText) {
      }
      return JSON.parse(decryptedText);
    } catch (e) {
      return null;
    }
  }

  private setItem(key: string, value: any): void {
    try {
      const encryptedData = this.encrypt(value);
      sessionStorage.setItem(key, encryptedData);
    } catch (e) {
    }
  }

  private getItem(key: string): any {
    try {
      const encryptedData = sessionStorage.getItem(key);
      if (encryptedData) {
        const decryptedData = this.decrypt(encryptedData);
        return decryptedData;
      }
    } catch (e) {
    }
    return null;
  }

    public setformDetails(data: any): void {
    this.setItem('formdetails', data)
  }

    public getformDetails(): string | null {
    const firstLogin = this.getItem('formdetails');
    return firstLogin || null;
  }

  public setfirstLogin(data: boolean): void {
    this.setItem('firstLogin', data)
  }

  public getfirstLogin(): string | null {
    const firstLogin = this.getItem('firstLogin');
    return firstLogin || null;
  }

  public setCrawlID(data: string): void {
    this.setItem('crawlID', data)
  }

  public getCrawlID(): string | null {
    const crawlId = this.getItem('crawlID');
    return crawlId || null;
  }

  public clearcrawlID(): void {
    sessionStorage.removeItem('crawlID');
  }

  public setAccessToken(token: string): void {
    this.setItem('accessToken', token);
  }

  public getAccessToken(): string | null {
    const accessToken = this.getItem('accessToken');
    return accessToken || null;
  }

  public setUserDetails(userDetails: any): void {
    this.setItem('userDetails', userDetails);
  }

  public getUserDetails(): any | null {
    return this.getItem('userDetails');
  }

  public clearSessionStore(): void {
    sessionStorage.clear();
    localStorage.clear()
  }

}
