import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface GithubRepo {
  stargazers_count: number;
}

@Injectable({
  providedIn: 'root'
})
export class GithubService {

  // Direct GitHub API (no proxy = no parse issues)
  private apiUrl =
    'https://api.github.com/repos/GramosoftAI/GcrawlAI';

  constructor(private http: HttpClient) {}

  getStars(): Observable<GithubRepo> {
    return this.http.get<GithubRepo>(this.apiUrl);
  }
}