import { environment } from "src/environement/environemet";

export const URLS = Object({
    // login 
    signup:`${environment.apiUrl}/auth/signup/send-otp`,
    verifyOtp:`${environment.apiUrl}/auth/signup/verify-otp`,
    signin: `${environment.apiUrl}/auth/signin`,
    config: `${environment.apiUrl}/crawler`,
    contact: `${environment.apiUrl}/contact`,
    report_Issue: `${environment.apiUrl}/report-issue`,
    markdown_Details: `${environment.apiUrl}/crawl/get/content`,
    user_history: `${environment.apiUrl}/crawler/paths`,
    userhistory_path_id: `${environment.apiUrl}/crawls/user`
});