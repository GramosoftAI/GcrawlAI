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
        self.from_name = smtp_config.get('from_name', 'Authentication System')
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
                    
                    <p>If you didn't request this verification, please ignore this email or contact support if you have concerns.</p>
                    
                    <div class="warning">
                        🔒 Security Notice: Never share this OTP with anyone. Our team will never ask for your OTP.
                    </div>
                </div>
                <div class="footer">
                    <p>This is an automated email. Please do not reply.</p>
                    <p>&copy; {datetime.now().year} Authentication System. All rights reserved.</p>
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
        © {datetime.now().year} Authentication System. All rights reserved.
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
                    <p>&copy; {datetime.now().year} Authentication System. All rights reserved.</p>
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
        
        If you didn't request a password reset, please ignore this email or contact support if you have concerns.
        
        For your security, this link can only be used once.
        
        ---
        This is an automated email. Please do not reply.
        © {datetime.now().year} Authentication System. All rights reserved.
        """
        
        subject = "Password Reset Request - Authentication System"
        
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
                    
                    <p>Here's what you can do next:</p>
                    <ul>
                        <li>Complete your profile</li>
                        <li>Explore the dashboard</li>
                        <li>Start using our services</li>
                    </ul>
                    
                    <p>If you have any questions or need assistance, our support team is always here to help.</p>
                    
                    <p>Thank you for choosing us!</p>
                    
                    <p>Best regards,<br>
                    <strong class="highlight">The Authentication System Team</strong></p>
                </div>
                <div class="footer">
                    <p>This is an automated email. Please do not reply.</p>
                    <p>&copy; {datetime.now().year} Authentication System. All rights reserved.</p>
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
        The Authentication System Team
        
        ---
        This is an automated email. Please do not reply.
        © {datetime.now().year} Authentication System. All rights reserved.
        """
        
        subject = "Welcome to Authentication System! 🎉"
        
        return self.send_email(to_email, subject, html_content, text_content)