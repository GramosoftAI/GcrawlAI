import { environment } from "src/environement/environemet";

export const URLS = Object({
    // login 
    signup:`${environment.apiUrl}/auth/signup/send-otp`,
    verifyOtp:`${environment.apiUrl}/auth/signup/verify-otp`,
    signin: `${environment.apiUrl}/auth/signin`,
    config: `${environment.apiUrl}/crawler`,
    markdown_Details: `${environment.apiUrl}/crawl/markdown`
});