#!/usr/bin/env python3

"""
Email Service for Authentication System

Handles sending emails for:
- Signup OTP verification
- Password reset with encrypted token
- Welcome emails for new users

Uses SMTP configuration from config.yaml.
Gracefully handles cases when SMTP is not configured.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmailService:
    """Email service for sending authentication-related notifications"""
    
    def __init__(self, smtp_config: Dict[str, Any]):
        """
        Initialize email service
        
        Args:
            smtp_config: SMTP configuration dictionary containing:
                - host: SMTP server host
                - port: SMTP server port
                - username: SMTP username
                - password: SMTP password
                - from_email: Sender email address
                - from_name: Sender name
                - use_tls: Whether to use TLS (default: True)
                - reset_password_url: Base URL for password reset page (optional)
        """
        self.smtp_host = smtp_config.get('host', 'smtp.gmail.com')
        self.smtp_port = smtp_config.get('port', 587)
        self.smtp_username = smtp_config.get('username')
        self.smtp_password = smtp_config.get('password')
        self.from_email = smtp_config.get('from_email', self.smtp_username)
        self.from_name = smtp_config.get('from_name', 'GcrawlAI')
        self.use_tls = smtp_config.get('use_tls', True)
        self.reset_password_url = smtp_config.get('reset_password_url', 'http://localhost:3000/reset-password')
        
        # Check if SMTP is properly configured
        self.is_configured = bool(
            self.smtp_host and 
            self.smtp_username and 
            self.smtp_password
        )
        
        if not self.is_configured:
            logger.warning("⚠ Email service not fully configured. Email sending will be disabled.")
        else:
            logger.info("✓ Email service configured successfully")
    
    def send_email(self, to_email: str, subject: str, 
                   html_content: str, text_content: Optional[str] = None) -> bool:
        """
        Send an email
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML content of the email
            text_content: Plain text content (optional)
        
        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.is_configured:
            logger.warning(f"⚠ Email service not configured. Skipping email to {to_email}")
            logger.info(f"Email would have been sent to {to_email} with subject: {subject}")
            return False
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = to_email
            msg['Subject'] = subject
            msg['Date'] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S %z")
            
            # Add plain text version if provided
            if text_content:
                part1 = MIMEText(text_content, 'plain', 'utf-8')
                msg.attach(part1)
            
            # Add HTML version
            part2 = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(part2)
            
            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"✓ Email sent successfully to {to_email}")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"✗ SMTP authentication failed: {e}")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"✗ SMTP error sending email to {to_email}: {e}")
            return False
        except Exception as e:
            logger.error(f"✗ Failed to send email to {to_email}: {e}", exc_info=True)
            return False
    
    def send_signup_otp_email(self, to_email: str, to_name: str, otp: str) -> bool:
        """
        Send signup OTP verification email
        
        Args:
            to_email: Recipient email address
            to_name: Recipient name
            otp: 5-digit OTP code
        
        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.is_configured:
            logger.warning(f"⚠ Email not sent to {to_email}. SMTP not configured.")
            logger.info(f"📧 Signup OTP for {to_email}: {otp}")
            return False
        
        # Create HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    margin: 0;
                    padding: 0;
                    background-color: #f4f4f4;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #ffffff;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px 20px;
                    text-align: center;
                    border-radius: 10px 10px 0 0;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 28px;
                    font-weight: 600;
                }}
                .content {{
                    background-color: #f9f9f9;
                    padding: 40px 30px;
                    border-radius: 0 0 10px 10px;
                }}
                .content h2 {{
                    color: #333;
                    margin-top: 0;
                    font-size: 22px;
                }}
                .otp-box {{
                    background-color: #fff;
                    padding: 25px;
                    text-align: center;
                    font-size: 36px;
                    font-weight: bold;
                    letter-spacing: 10px;
                    color: #667eea;
                    border: 3px dashed #667eea;
                    margin: 30px 0;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .info-box {{
                    background-color: #fff3cd;
                    border-left: 4px solid #ffc107;
                    padding: 15px;
                    margin: 20px 0;
                    border-radius: 4px;
                }}
                .warning {{
                    background-color: #f8d7da;
                    border-left: 4px solid #dc3545;
                    padding: 15px;
                    margin: 20px 0;
                    border-radius: 4px;
                    color: #721c24;
                    font-weight: 600;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #ddd;
                    color: #666;
                    font-size: 12px;
                }}
                .footer p {{
                    margin: 5px 0;
                }}
                p {{
                    margin: 15px 0;
                    line-height: 1.6;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔐 Email Verification</h1>
                </div>
                <div class="content">
                    <h2>Hello {to_name},</h2>
                    <p>Thank you for signing up! To complete your registration, please use the following One-Time Password (OTP):</p>
                    
                    <div class="otp-box">
                        {otp}
                    </div>
                    
                    <div class="info-box">
                        <strong>⏰ Important:</strong> This OTP is valid for <strong>5 minutes</strong> only.
                    </div>
                    
                    <p>Enter this code in the verification page to activate your account.</p>
                    
                    <p>If you didn't request this verification, please ignore this email.</p>
                    
                    <div class="warning">
                        🔒 Security Notice: Never share this OTP with anyone. Our team will never ask for your OTP.
                    </div>
                </div>
                <div class="footer">
                    <p>This is an automated email. Please do not reply.</p>
                    <p>&copy; {datetime.now().year} GcrawlAI. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text version
        text_content = f"""
        Email Verification
        
        Hello {to_name},
        
        Thank you for signing up! Your One-Time Password (OTP) for email verification is:
        
        {otp}
        
        This OTP is valid for 5 minutes only.
        
        Enter this code in the verification page to activate your account.
        
        If you didn't request this verification, please ignore this email.
        
        SECURITY NOTICE: Never share this OTP with anyone.
        
        ---
        This is an automated email. Please do not reply.
        © {datetime.now().year} GcrawlAI. All rights reserved.
        """
        
        subject = f"Your Verification Code: {otp}"
        
        return self.send_email(to_email, subject, html_content, text_content)
    
    def send_password_reset_email(self, to_email: str, to_name: str, 
                                  reset_url_base: str = None,
                                  encrypted_token: str = None) -> bool:
        """
        Send password reset email with encrypted token
        
        Args:
            to_email: Recipient email address
            to_name: Recipient name
            reset_url_base: Base URL for password reset page
            encrypted_token: Encrypted token containing user email (URL-safe)
        
        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.is_configured:
            logger.warning(f"⚠ Email not sent to {to_email}. SMTP not configured.")
            logger.info(f"📧 Password reset requested for: {to_email}")
            if encrypted_token:
                logger.info(f"🔑 Encrypted token: {encrypted_token}")
            return False
        
        # Validate that encrypted_token is provided
        if not encrypted_token:
            logger.error("✗ Cannot send password reset email: encrypted_token is required")
            return False
        
        # Use provided reset URL or default from config
        if not reset_url_base:
            reset_url_base = self.reset_password_url
        
        # Include encrypted token as query parameter
        reset_link = f"{reset_url_base}?token={encrypted_token}"
        
        # Create HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    margin: 0;
                    padding: 0;
                    background-color: #f4f4f4;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #ffffff;
                }}
                .header {{
                    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                    color: white;
                    padding: 30px 20px;
                    text-align: center;
                    border-radius: 10px 10px 0 0;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 28px;
                    font-weight: 600;
                }}
                .content {{
                    background-color: #f9f9f9;
                    padding: 40px 30px;
                    border-radius: 0 0 10px 10px;
                }}
                .content h2 {{
                    color: #333;
                    margin-top: 0;
                    font-size: 22px;
                }}
                .button {{
                    display: inline-block;
                    padding: 15px 40px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    text-decoration: none;
                    border-radius: 50px;
                    margin: 25px 0;
                    font-weight: 600;
                    font-size: 16px;
                    text-align: center;
                    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
                    transition: all 0.3s ease;
                }}
                .button:hover {{
                    box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
                    transform: translateY(-2px);
                }}
                .info-box {{
                    background-color: #d1ecf1;
                    border-left: 4px solid #17a2b8;
                    padding: 15px;
                    margin: 20px 0;
                    border-radius: 4px;
                }}
                .warning {{
                    background-color: #fff3cd;
                    border-left: 4px solid #ffc107;
                    padding: 15px;
                    margin: 20px 0;
                    border-radius: 4px;
                    color: #856404;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #ddd;
                    color: #666;
                    font-size: 12px;
                }}
                .footer p {{
                    margin: 5px 0;
                }}
                p {{
                    margin: 15px 0;
                    line-height: 1.6;
                }}
                .link-box {{
                    background-color: #f8f9fa;
                    padding: 15px;
                    border-radius: 5px;
                    word-break: break-all;
                    font-size: 12px;
                    color: #666;
                    margin: 15px 0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔑 Password Reset Request</h1>
                </div>
                <div class="content">
                    <h2>Hello {to_name},</h2>
                    <p>We received a request to reset your password. Click the button below to create a new password:</p>
                    
                    <div style="text-align: center;">
                        <a href="{reset_link}" class="button">Reset Your Password</a>
                    </div>
                    
                    <div class="info-box">
                        <strong>⏰ Valid for 24 hours:</strong> This password reset link will expire in 24 hours for security reasons.
                    </div>
                    
                    <p>If the button doesn't work, copy and paste this link into your browser:</p>
                    <div class="link-box">
                        {reset_link}
                    </div>
                    
                    <div class="warning">
                        <strong>⚠️ Didn't request this?</strong><br>
                        If you didn't request a password reset, please ignore this email or contact support if you have concerns about your account security.
                    </div>
                    
                    <p>For your security, this link can only be used once and will expire after 24 hours.</p>
                </div>
                <div class="footer">
                    <p>This is an automated email. Please do not reply.</p>
                    <p>&copy; {datetime.now().year} GcrawlAI. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text version
        text_content = f"""
        Password Reset Request
        
        Hello {to_name},
        
        We received a request to reset your password.
        
        Please click the following link to reset your password:
        {reset_link}
        
        This link will remain valid for 24 hours.
        
        If you didn't request a password reset, please ignore this email.
        
        For your security, this link can only be used once.
        
        ---
        This is an automated email. Please do not reply.
        © {datetime.now().year} GcrawlAI. All rights reserved.
        """
        
        subject = "Password Reset Request - GcrawlAI"
        
        return self.send_email(to_email, subject, html_content, text_content)
    
    def send_welcome_email(self, to_email: str, to_name: str) -> bool:
        """
        Send welcome email to new users
        
        Args:
            to_email: Recipient email address
            to_name: Recipient name
        
        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.is_configured:
            logger.warning(f"⚠ Email not sent to {to_email}. SMTP not configured.")
            logger.info(f"📧 Welcome email would be sent to: {to_email}")
            return False
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    margin: 0;
                    padding: 0;
                    background-color: #f4f4f4;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #ffffff;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 40px 20px;
                    text-align: center;
                    border-radius: 10px 10px 0 0;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 32px;
                    font-weight: 600;
                }}
                .emoji {{
                    font-size: 60px;
                    margin-bottom: 10px;
                }}
                .content {{
                    background-color: #f9f9f9;
                    padding: 40px 30px;
                    border-radius: 0 0 10px 10px;
                }}
                .content h2 {{
                    color: #333;
                    margin-top: 0;
                    font-size: 24px;
                }}
                .feature-box {{
                    background-color: #fff;
                    padding: 20px;
                    margin: 20px 0;
                    border-radius: 8px;
                    border-left: 4px solid #667eea;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #ddd;
                    color: #666;
                    font-size: 12px;
                }}
                .footer p {{
                    margin: 5px 0;
                }}
                p {{
                    margin: 15px 0;
                    line-height: 1.6;
                }}
                .highlight {{
                    color: #667eea;
                    font-weight: 600;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="emoji">🎉</div>
                    <h1>Welcome Aboard!</h1>
                </div>
                <div class="content">
                    <h2>Hello {to_name},</h2>
                    <p>Welcome to our platform! We're thrilled to have you join our community.</p>
                    
                    <div class="feature-box">
                        <p><strong>✓ Your account has been successfully created!</strong></p>
                        <p>You can now access all features and start using the platform.</p>
                    </div>
                    <p>Thank you for choosing us!</p>
                    
                    <p>Best regards,<br>
                    <strong class="highlight">The GcrawlAI Team</strong></p>
                </div>
                <div class="footer">
                    <p>This is an automated email. Please do not reply.</p>
                    <p>&copy; {datetime.now().year} GcrawlAI. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        Welcome Aboard!
        
        Hello {to_name},
        
        Welcome to our platform! We're thrilled to have you join our community.
        
        Your account has been successfully created!
        
        You can now access all features and start using the platform.
        
        Here's what you can do next:
        - Complete your profile
        - Explore the dashboard
        - Start using our services
        
        If you have any questions or need assistance, our support team is always here to help.
        
        Thank you for choosing us!
        
        Best regards,
        The GcrawlAI Team
        
        ---
        This is an automated email. Please do not reply.
        © {datetime.now().year} GcrawlAI. All rights reserved.
        """
        
        subject = "Welcome to GcrawlAI! 🎉"
        
        return self.send_email(to_email, subject, html_content, text_content)
    
    def send_contact_email(
        self,
        to_email: str,
        name: str,
        email: str,
        mobile: str,
        company: str,
        country: str | None,
        message: str,
    ) -> bool:
        """
        Send a professional contact-form notification email.

        Args:
            to_email : Recipient (internal team) email address — jeevae@gramosoft.in
            name     : Sender's full name
            email    : Sender's email address
            mobile   : Sender's mobile number
            company  : Sender's company name
            country  : Sender's country (optional)
            message  : Enquiry / project description

        Returns:
            True if email sent successfully, False otherwise
        """
        country_display = country if country else "Not specified"
        submitted_at = datetime.now().strftime("%d %b %Y, %I:%M %p")

        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>New Contact Enquiry — GcrawlAI</title>
            <style>
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #f0f2f5;
                    color: #1a1a2e;
                    padding: 30px 20px;
                }}
                .wrapper {{
                    max-width: 640px;
                    margin: 0 auto;
                }}
                /* ── Header ── */
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    border-radius: 12px 12px 0 0;
                    padding: 36px 32px;
                    text-align: center;
                }}
                .header .logo-text {{
                    font-size: 26px;
                    font-weight: 700;
                    color: #ffffff;
                    letter-spacing: 1px;
                }}
                .header .badge {{
                    display: inline-block;
                    margin-top: 10px;
                    background: rgba(255,255,255,0.2);
                    color: #fff;
                    font-size: 13px;
                    font-weight: 600;
                    padding: 4px 14px;
                    border-radius: 50px;
                    letter-spacing: 0.5px;
                }}
                /* ── Alert banner ── */
                .alert-banner {{
                    background: #fff8e1;
                    border-left: 5px solid #f59e0b;
                    padding: 14px 20px;
                    font-size: 14px;
                    color: #7c5e00;
                    font-weight: 600;
                }}
                /* ── Body card ── */
                .card {{
                    background: #ffffff;
                    padding: 36px 32px;
                    border-radius: 0 0 12px 12px;
                    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
                }}
                .card h2 {{
                    font-size: 20px;
                    color: #374151;
                    margin-bottom: 6px;
                }}
                .card .subtitle {{
                    font-size: 13px;
                    color: #9ca3af;
                    margin-bottom: 28px;
                }}
                /* ── Info grid ── */
                .info-grid {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 16px;
                    margin-bottom: 24px;
                }}
                .info-item {{
                    background: #f8fafc;
                    border: 1px solid #e5e7eb;
                    border-radius: 8px;
                    padding: 14px 18px;
                }}
                .info-item .label {{
                    font-size: 10px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    color: #6b7280;
                    margin-bottom: 5px;
                }}
                .info-item .value {{
                    font-size: 15px;
                    font-weight: 600;
                    color: #111827;
                    word-break: break-word;
                }}
                .info-item.full-width {{
                    grid-column: 1 / -1;
                }}
                /* ── Message box ── */
                .message-box {{
                    background: #f3f4f6;
                    border-left: 4px solid #667eea;
                    border-radius: 0 8px 8px 0;
                    padding: 20px 22px;
                    margin-bottom: 28px;
                }}
                .message-box .label {{
                    font-size: 10px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    color: #6b7280;
                    margin-bottom: 10px;
                }}
                .message-box .text {{
                    font-size: 15px;
                    color: #374151;
                    line-height: 1.7;
                    white-space: pre-wrap;
                    word-break: break-word;
                }}
                /* ── Reply CTA ── */
                .cta-row {{
                    text-align: center;
                    margin-bottom: 24px;
                }}
                .cta-button {{
                    display: inline-block;
                    padding: 14px 36px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: #ffffff;
                    text-decoration: none;
                    border-radius: 50px;
                    font-size: 15px;
                    font-weight: 600;
                    letter-spacing: 0.3px;
                    box-shadow: 0 4px 14px rgba(102, 126, 234, 0.45);
                }}
                /* ── Divider ── */
                .divider {{
                    border: none;
                    border-top: 1px solid #e5e7eb;
                    margin: 24px 0;
                }}
                /* ── Meta info ── */
                .meta {{
                    font-size: 12px;
                    color: #9ca3af;
                    text-align: center;
                    line-height: 1.8;
                }}
                /* ── Footer ── */
                .footer {{
                    text-align: center;
                    margin-top: 24px;
                    font-size: 12px;
                    color: #9ca3af;
                    line-height: 1.8;
                }}
            </style>
        </head>
        <body>
        <div class="wrapper">

            <!-- Header -->
            <div class="header">
                <div class="logo-text">🕷️ GcrawlAI</div>
                <div class="badge">📬 New Contact Enquiry</div>
            </div>

            <!-- Alert Banner -->
            <div class="alert-banner">
                ⚡ A new project enquiry has just been submitted — please respond within 24 hours.
            </div>

            <!-- Card -->
            <div class="card">
                <h2>New Enquiry Details</h2>
                <p class="subtitle">Submitted on {submitted_at} (IST)</p>

                <!-- Info Grid -->
                <div class="info-grid">
                    <div class="info-item">
                        <div class="label">👤 Full Name</div>
                        <div class="value">{name}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">📧 Email Address</div>
                        <div class="value">{email}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">📱 Mobile Number</div>
                        <div class="value">{mobile}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">🏢 Company</div>
                        <div class="value">{company}</div>
                    </div>
                    <div class="info-item full-width">
                        <div class="label">🌍 Country</div>
                        <div class="value">{country_display}</div>
                    </div>
                </div>

                <!-- Message -->
                <div class="message-box">
                    <div class="label">💬 Project Message</div>
                    <div class="text">{message}</div>
                </div>

                <!-- Reply CTA -->
                <div class="cta-row">
                    <a href="mailto:{email}?subject=Re: Your GcrawlAI Enquiry"
                       class="cta-button">
                        ↩ Reply to {name}
                    </a>
                </div>

                <hr class="divider">

                <!-- Meta -->
                <div class="meta">
                    Submitted via GcrawlAI Contact Form &nbsp;|&nbsp; {submitted_at} (IST)<br>
                    From IP: <em>Not captured</em>
                </div>
            </div>

            <!-- Footer -->
            <div class="footer">
                This is an automated internal notification. Do not reply to this email directly.<br>
                &copy; {datetime.now().year} Gramosoft Private Limited. All rights reserved.
            </div>

        </div>
        </body>
        </html>
        """

        text_content = f"""
NEW CONTACT ENQUIRY — GcrawlAI
{'=' * 50}
Submitted : {submitted_at} (IST)

CONTACT DETAILS
---------------
Name    : {name}
Email   : {email}
Mobile  : {mobile}
Company : {company}
Country : {country_display}

PROJECT MESSAGE
---------------
{message}

{'=' * 50}
Reply directly to: {email}
{'=' * 50}
This is an automated internal notification.
© {datetime.now().year} Gramosoft Private Limited. All rights reserved.
        """

        subject = f"[GcrawlAI Enquiry] {name} from {company} — New Contact Form Submission"

        logger.info(f"[ContactUs] Sending enquiry email to {to_email} for '{name}' <{email}>")
        return self.send_email(to_email, subject, html_content, text_content)

    def send_report_issue_email(
        self,
        to_email: str,
        url_affected: str,
        issue_related_to: list,
        explanation: str,
        report_id: int = None,
    ) -> bool:
        """
        Send a report-issue notification email to the admin.

        Args:
            to_email: Admin email address
            url_affected: The URL that has the issue
            issue_related_to: List of issue category strings
            explanation: Free-text explanation of the issue
            report_id: Optional DB row id for reference

        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.is_configured:
            logger.warning(f"⚠ Email not sent to {to_email}. SMTP not configured.")
            logger.info(f"📧 Issue report would have been sent to admin: {to_email}")
            return False

        issues_html = "".join(
            f"<li style='margin:4px 0;'>{issue}</li>" for issue in issue_related_to
        )
        issues_text = ", ".join(issue_related_to)
        report_ref = f"#{report_id}" if report_id else "N/A"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    margin: 0;
                    padding: 0;
                    background-color: #f4f4f4;
                }}
                .container {{
                    max-width: 620px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #ffffff;
                }}
                .header {{
                    background: linear-gradient(135deg, #f5576c 0%, #f093fb 100%);
                    color: white;
                    padding: 30px 20px;
                    text-align: center;
                    border-radius: 10px 10px 0 0;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 26px;
                    font-weight: 700;
                }}
                .badge {{
                    display: inline-block;
                    background: rgba(255,255,255,0.2);
                    border-radius: 20px;
                    padding: 4px 14px;
                    font-size: 13px;
                    margin-top: 8px;
                    letter-spacing: 0.5px;
                }}
                .content {{
                    background-color: #f9f9f9;
                    padding: 36px 30px;
                    border-radius: 0 0 10px 10px;
                }}
                .field-label {{
                    font-size: 11px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    color: #888;
                    margin-bottom: 4px;
                }}
                .field-value {{
                    background: #fff;
                    border: 1px solid #e0e0e0;
                    border-radius: 6px;
                    padding: 12px 16px;
                    margin-bottom: 20px;
                    font-size: 15px;
                    word-break: break-all;
                }}
                .field-value.url {{
                    color: #667eea;
                    font-weight: 600;
                }}
                .field-value ul {{
                    margin: 0;
                    padding-left: 20px;
                }}
                .explanation-box {{
                    background: #fff;
                    border-left: 4px solid #f5576c;
                    border-radius: 0 6px 6px 0;
                    padding: 14px 16px;
                    margin-bottom: 20px;
                    font-size: 15px;
                    white-space: pre-wrap;
                }}
                .meta {{
                    font-size: 12px;
                    color: #aaa;
                    margin-top: 4px;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 16px;
                    border-top: 1px solid #ddd;
                    color: #999;
                    font-size: 12px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🚨 New Issue Report</h1>
                    <div class="badge">Report {report_ref}</div>
                </div>
                <div class="content">
                    <p style="margin-top:0;">A new issue has been submitted. Please review the details below.</p>

                    <div class="field-label">URL Affected</div>
                    <div class="field-value url">{url_affected}</div>

                    <div class="field-label">Issue Related To</div>
                    <div class="field-value">
                        <ul>{issues_html}</ul>
                    </div>

                    <div class="field-label">Explanation</div>
                    <div class="explanation-box">{explanation}</div>

                    <div class="meta">Submitted on {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}</div>
                </div>
                <div class="footer">
                    <p>This is an automated notification from GcrawlAI.</p>
                    <p>&copy; {datetime.now().year} GcrawlAI. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
New Issue Report {report_ref}
{'=' * 40}

URL Affected:
{url_affected}

Issue Related To:
{issues_text}

Explanation:
{explanation}

Submitted: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}

---
GcrawlAI automated notification.
        """

        subject = f"🚨 Issue Report {report_ref}: {url_affected[:60]}"

        return self.send_email(to_email, subject, html_content, text_content)

    def send_contact_email(
        self,
        to_email: str,
        name: str,
        email: str,
        mobile: str,
        company: str,
        country: str | None,
        message: str,
    ) -> bool:
        """
        Send a professional contact-form notification email.

        Args:
            to_email : Recipient (internal team) email address — jeevae@gramosoft.in
            name     : Sender's full name
            email    : Sender's email address
            mobile   : Sender's mobile number
            company  : Sender's company name
            country  : Sender's country (optional)
            message  : Enquiry / project description

        Returns:
            True if email sent successfully, False otherwise
        """
        country_display = country if country else "Not specified"
        submitted_at = datetime.now().strftime("%d %b %Y, %I:%M %p")

        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>New Contact Enquiry — GcrawlAI</title>
            <style>
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #f0f2f5;
                    color: #1a1a2e;
                    padding: 30px 20px;
                }}
                .wrapper {{
                    max-width: 640px;
                    margin: 0 auto;
                }}
                /* ── Header ── */
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    border-radius: 12px 12px 0 0;
                    padding: 36px 32px;
                    text-align: center;
                }}
                .header .logo-text {{
                    font-size: 26px;
                    font-weight: 700;
                    color: #ffffff;
                    letter-spacing: 1px;
                }}
                .header .badge {{
                    display: inline-block;
                    margin-top: 10px;
                    background: rgba(255,255,255,0.2);
                    color: #fff;
                    font-size: 13px;
                    font-weight: 600;
                    padding: 4px 14px;
                    border-radius: 50px;
                    letter-spacing: 0.5px;
                }}
                /* ── Alert banner ── */
                .alert-banner {{
                    background: #fff8e1;
                    border-left: 5px solid #f59e0b;
                    padding: 14px 20px;
                    font-size: 14px;
                    color: #7c5e00;
                    font-weight: 600;
                }}
                /* ── Body card ── */
                .card {{
                    background: #ffffff;
                    padding: 36px 32px;
                    border-radius: 0 0 12px 12px;
                    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
                }}
                .card h2 {{
                    font-size: 20px;
                    color: #374151;
                    margin-bottom: 6px;
                }}
                .card .subtitle {{
                    font-size: 13px;
                    color: #9ca3af;
                    margin-bottom: 28px;
                }}
                /* ── Info grid ── */
                .info-grid {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 16px;
                    margin-bottom: 24px;
                }}
                .info-item {{
                    background: #f8fafc;
                    border: 1px solid #e5e7eb;
                    border-radius: 8px;
                    padding: 14px 18px;
                }}
                .info-item .label {{
                    font-size: 10px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    color: #6b7280;
                    margin-bottom: 5px;
                }}
                .info-item .value {{
                    font-size: 15px;
                    font-weight: 600;
                    color: #111827;
                    word-break: break-word;
                }}
                .info-item.full-width {{
                    grid-column: 1 / -1;
                }}
                /* ── Message box ── */
                .message-box {{
                    background: #f3f4f6;
                    border-left: 4px solid #667eea;
                    border-radius: 0 8px 8px 0;
                    padding: 20px 22px;
                    margin-bottom: 28px;
                }}
                .message-box .label {{
                    font-size: 10px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    color: #6b7280;
                    margin-bottom: 10px;
                }}
                .message-box .text {{
                    font-size: 15px;
                    color: #374151;
                    line-height: 1.7;
                    white-space: pre-wrap;
                    word-break: break-word;
                }}
                /* ── Reply CTA ── */
                .cta-row {{
                    text-align: center;
                    margin-bottom: 24px;
                }}
                .cta-button {{
                    display: inline-block;
                    padding: 14px 36px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: #ffffff;
                    text-decoration: none;
                    border-radius: 50px;
                    font-size: 15px;
                    font-weight: 600;
                    letter-spacing: 0.3px;
                    box-shadow: 0 4px 14px rgba(102, 126, 234, 0.45);
                }}
                /* ── Divider ── */
                .divider {{
                    border: none;
                    border-top: 1px solid #e5e7eb;
                    margin: 24px 0;
                }}
                /* ── Meta info ── */
                .meta {{
                    font-size: 12px;
                    color: #9ca3af;
                    text-align: center;
                    line-height: 1.8;
                }}
                /* ── Footer ── */
                .footer {{
                    text-align: center;
                    margin-top: 24px;
                    font-size: 12px;
                    color: #9ca3af;
                    line-height: 1.8;
                }}
            </style>
        </head>
        <body>
        <div class="wrapper">

            <!-- Header -->
            <div class="header">
                <div class="logo-text">🕷️ GcrawlAI</div>
                <div class="badge">📬 New Contact Enquiry</div>
            </div>

            <!-- Alert Banner -->
            <div class="alert-banner">
                ⚡ A new project enquiry has just been submitted — please respond within 24 hours.
            </div>

            <!-- Card -->
            <div class="card">
                <h2>New Enquiry Details</h2>
                <p class="subtitle">Submitted on {submitted_at} (IST)</p>

                <!-- Info Grid -->
                <div class="info-grid">
                    <div class="info-item">
                        <div class="label">👤 Full Name</div>
                        <div class="value">{name}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">📧 Email Address</div>
                        <div class="value">{email}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">📱 Mobile Number</div>
                        <div class="value">{mobile}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">🏢 Company</div>
                        <div class="value">{company}</div>
                    </div>
                    <div class="info-item full-width">
                        <div class="label">🌍 Country</div>
                        <div class="value">{country_display}</div>
                    </div>
                </div>

                <!-- Message -->
                <div class="message-box">
                    <div class="label">💬 Project Message</div>
                    <div class="text">{message}</div>
                </div>

                <!-- Reply CTA -->
                <div class="cta-row">
                    <a href="mailto:{email}?subject=Re: Your GcrawlAI Enquiry"
                       class="cta-button">
                        ↩ Reply to {name}
                    </a>
                </div>

                <hr class="divider">

                <!-- Meta -->
                <div class="meta">
                    Submitted via GcrawlAI Contact Form &nbsp;|&nbsp; {submitted_at} (IST)<br>
                    From IP: <em>Not captured</em>
                </div>
            </div>

            <!-- Footer -->
            <div class="footer">
                This is an automated internal notification. Do not reply to this email directly.<br>
                &copy; {datetime.now().year} Gramosoft Private Limited. All rights reserved.
            </div>

        </div>
        </body>
        </html>
        """

        text_content = f"""
NEW CONTACT ENQUIRY — GcrawlAI
{'=' * 50}
Submitted : {submitted_at} (IST)

CONTACT DETAILS
---------------
Name    : {name}
Email   : {email}
Mobile  : {mobile}
Company : {company}
Country : {country_display}

PROJECT MESSAGE
---------------
{message}

{'=' * 50}
Reply directly to: {email}
{'=' * 50}
This is an automated internal notification.
© {datetime.now().year} Gramosoft Private Limited. All rights reserved.
        """

        subject = f"[GcrawlAI Enquiry] {name} from {company} — New Contact Form Submission"

        logger.info(f"[ContactUs] Sending enquiry email to {to_email} for '{name}' <{email}>")
        return self.send_email(to_email, subject, html_content, text_content)