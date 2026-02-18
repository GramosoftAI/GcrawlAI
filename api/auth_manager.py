#!/usr/bin/env python3

"""
Authentication Manager - Core Business Logic

Provides core authentication operations including:
- Password hashing and verification with salt
- JWT token creation and verification
- OTP-based email verification for signup
- Encrypted token-based password reset
- User management and database operations

All sensitive data is read from config.yaml.
No hardcoded secrets anywhere.
"""

import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
import secrets
import hashlib
import base64
import yaml
from pathlib import Path
import jwt
from cryptography.fernet import Fernet
import os
import re
from dotenv import load_dotenv

from api.email_service import EmailService

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==================== ENCRYPTION UTILITIES ====================

def encrypt_email(email: str, encryption_key: str) -> str:
    """
    Encrypt email address using Fernet symmetric encryption
    
    Args:
        email: Email address to encrypt
        encryption_key: Base64-encoded encryption key
    
    Returns:
        URL-safe encrypted token
    """
    try:
        # Ensure key is bytes
        if isinstance(encryption_key, str):
            key_bytes = encryption_key.encode('utf-8')
        else:
            key_bytes = encryption_key
        
        fernet = Fernet(key_bytes)
        encrypted = fernet.encrypt(email.encode('utf-8'))
        
        # Return URL-safe base64 encoded string
        return base64.urlsafe_b64encode(encrypted).decode('utf-8')
    
    except Exception as e:
        logger.error(f"Encryption error: {e}", exc_info=True)
        raise


def decrypt_email(encrypted_token: str, encryption_key: str) -> Optional[str]:
    """
    Decrypt email address from encrypted token
    
    Args:
        encrypted_token: URL-safe encrypted token
        encryption_key: Base64-encoded encryption key
    
    Returns:
        Decrypted email address or None if decryption fails
    """
    try:
        # Ensure key is bytes
        if isinstance(encryption_key, str):
            key_bytes = encryption_key.encode('utf-8')
        else:
            key_bytes = encryption_key
        
        fernet = Fernet(key_bytes)
        
        # Decode from URL-safe base64
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_token.encode('utf-8'))
        
        # Decrypt
        decrypted = fernet.decrypt(encrypted_bytes)
        return decrypted.decode('utf-8')
    
    except Exception as e:
        logger.error(f"Decryption error: {e}", exc_info=True)
        return None


# ==================== PASSWORD HASHING ====================

class PasswordHasher:
    """Handles password hashing and verification using SHA-256 with salt"""
    
    @staticmethod
    def generate_salt(length: int = 32) -> str:
        """
        Generate a random salt
        
        Args:
            length: Length of salt in bytes
        
        Returns:
            Hex-encoded salt string
        """
        return secrets.token_hex(length)
    
    @staticmethod
    def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
        """
        Hash password with salt using SHA-256
        
        Args:
            password: Plain text password
            salt: Optional salt (generates new one if not provided)
        
        Returns:
            Tuple of (hashed_password, salt)
        """
        if salt is None:
            salt = PasswordHasher.generate_salt()
        
        # Combine password and salt
        salted_password = f"{password}{salt}"
        
        # Hash using SHA-256
        hashed = hashlib.sha256(salted_password.encode('utf-8')).hexdigest()
        
        return hashed, salt
    
    @staticmethod
    def verify_password(password: str, hashed_password: str, salt: str) -> bool:
        """
        Verify password against hash
        
        Args:
            password: Plain text password to verify
            hashed_password: Stored password hash
            salt: Stored salt
        
        Returns:
            True if password matches, False otherwise
        """
        # Hash the provided password with the stored salt
        computed_hash, _ = PasswordHasher.hash_password(password, salt)
        
        # Compare hashes
        return computed_hash == hashed_password


# ==================== JWT MANAGER ====================

class JWTManager:
    """Handles JWT token creation and verification"""
    
    def __init__(self, secret_key: str, algorithm: str = "HS256", 
                 access_token_expire_minutes: int = 1440):
        """
        Initialize JWT manager
        
        Args:
            secret_key: Secret key for signing tokens
            algorithm: JWT algorithm (default: HS256)
            access_token_expire_minutes: Token expiration time in minutes
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
    
    def create_access_token(self, data: Dict[str, Any]) -> str:
        """
        Create JWT access token
        
        Args:
            data: Data to encode in token (e.g., user_id, email)
        
        Returns:
            Encoded JWT token
        """
        to_encode = data.copy()
        
        # Add expiration time
        expire = datetime.now() + timedelta(minutes=int(self.access_token_expire_minutes))
        to_encode.update({"exp": expire})
        
        # Encode token
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        
        return encoded_jwt
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify and decode JWT token
        
        Args:
            token: JWT token to verify
        
        Returns:
            Decoded token data or None if invalid/expired
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        
        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except jwt.InvalidTokenError:
            logger.warning("Invalid token")
            return None
        except Exception as e:
            logger.error(f"Token verification error: {e}", exc_info=True)
            return None


# ==================== AUTHENTICATION MANAGER ====================

class AuthManager:
    """Manages user authentication, registration, and password reset operations"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize authentication manager
        
        Args:
            config_path: Path to configuration file
        """
        self.config = self._load_config(config_path)
        
        # Load database configuration
        self.db_config = self.config.get('postgres', {})
        if not self.db_config:
            raise ValueError("PostgreSQL configuration not found in config.yaml")
        
        # Load security configuration
        security_config = self.config.get('security', {})
        if not security_config:
            raise ValueError("Security configuration not found in config.yaml")
        
        self.jwt_secret_key = security_config.get('jwt_secret_key')
        self.encryption_key = security_config.get('encryption_key')
        self.jwt_algorithm = security_config.get('jwt_algorithm', 'HS256')
        self.access_token_expire_minutes = security_config.get('access_token_expire_minutes', 1440)
        
        if not self.jwt_secret_key or not self.encryption_key:
            raise ValueError("JWT secret key and encryption key must be provided in config.yaml")
        
        # Initialize JWT manager
        self.jwt_manager = JWTManager(
            secret_key=self.jwt_secret_key,
            algorithm=self.jwt_algorithm,
            access_token_expire_minutes=self.access_token_expire_minutes
        )
        
        # Initialize password hasher
        self.password_hasher = PasswordHasher()
        
        # Load email service if configured
        self.email_service = None
        self._initialize_email_service()
        
        logger.info("✓ AuthManager initialized successfully")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """
        Load configuration from YAML file with environment variable substitution
        
        Args:
            config_path: Path to configuration file
        
        Returns:
            Configuration dictionary
        """
        try:
            config_file = Path(config_path)
            if not config_file.exists():
                raise FileNotFoundError(f"Configuration file not found: {config_path}")
            
            with open(config_file, 'r') as f:
                raw_config = yaml.safe_load(f)
            
            # Substitute environment variables
            config = self._substitute_env_vars(raw_config)
            
            logger.info(f"Configuration loaded from {config_path}")
            return config
        
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}", exc_info=True)
            raise
    
    @staticmethod
    def _substitute_env_vars(data):
        """
        Recursively substitute environment variables in configuration.
        Supports format: ${VAR_NAME} or ${VAR_NAME:default_value}
        """
        if isinstance(data, dict):
            return {key: AuthManager._substitute_env_vars(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [AuthManager._substitute_env_vars(item) for item in data]
        elif isinstance(data, str):
            # Pattern: ${VAR_NAME} or ${VAR_NAME:default_value}
            def replace_var(match):
                var_name = match.group(1)
                default_value = match.group(2)
                return os.getenv(var_name, default_value or "")
            
            return re.sub(r'\$\{([^:}]+)(?::([^}]*))?\}', replace_var, data)
        else:
            return data
    
    def _initialize_email_service(self):
        """Initialize email service if configured"""
        try:
            email_config = self.config.get('email', {})
            
            if email_config and email_config.get('host'):
                self.email_service = EmailService(email_config)
                logger.info("✓ Email service initialized")
            else:
                logger.warning("Email service not configured - emails will not be sent")
        
        except Exception as e:
            logger.warning(f"Failed to initialize email service: {e}")
            self.email_service = None
    
    def _get_db_connection(self):
        """
        Create and return a database connection
        
        Returns:
            psycopg2 connection object
        """
        try:
            conn = psycopg2.connect(
                host=self.db_config.get('host'),
                port=self.db_config.get('port'),
                database=self.db_config.get('database'),
                user=self.db_config.get('user'),
                password=self.db_config.get('password')
            )
            return conn
        
        except psycopg2.Error as e:
            logger.error(f"Database connection error: {e}", exc_info=True)
            raise ValueError(f"Database connection failed: {str(e)}")
    
    def generate_signup_otp(self, name: str, email: str, password: str) -> Tuple[bool, str, Optional[str]]:
        """
        Generate OTP for signup email verification
        
        Args:
            name: User's name
            email: User's email
            password: User's password (will be hashed and stored temporarily)
        
        Returns:
            Tuple of (success, message, otp)
        """
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Check if user already exists
            cursor.execute("SELECT user_id FROM users WHERE email = %s", (email.lower(),))
            if cursor.fetchone():
                cursor.close()
                conn.close()
                logger.warning(f"[FAILED] OTP generation failed: User already exists for {email}")
                return False, "User already exists with this email", None
            
            # Hash password
            hashed_password, salt = self.password_hasher.hash_password(password)
            
            # Generate 5-digit OTP
            otp = ''.join([str(secrets.randbelow(10)) for _ in range(5)])
            
            # Calculate expiry (5 minutes from now)
            expires_at = datetime.now() + timedelta(minutes=5)
            
            # Store OTP in signup_otps table
            cursor.execute("""
                INSERT INTO signup_otps (email, otp, name, password_hash, password_salt, expires_at, attempts, is_verified)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET
                    otp = EXCLUDED.otp,
                    name = EXCLUDED.name,
                    password_hash = EXCLUDED.password_hash,
                    password_salt = EXCLUDED.password_salt,
                    expires_at = EXCLUDED.expires_at,
                    attempts = 0,
                    is_verified = false
            """, (email.lower(), otp, name, hashed_password, salt, expires_at, 0, False))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            # Send OTP email if email service is configured
            if self.email_service:
                try:
                    email_sent = self.email_service.send_signup_otp_email(
                        email,
                        name,
                        otp
                    )
                    if email_sent:
                        logger.info(f"✓ OTP email sent successfully to {email}")
                    else:
                        logger.warning(f"✗ Failed to send OTP email to {email}")
                except Exception as e:
                    logger.error(f"Email sending error: {e}", exc_info=True)
            
            logger.info(f"[SUCCESS] OTP generated successfully for: {email}")
            
            return True, f"OTP sent to {email}. Valid for 5 minutes.", otp
        
        except psycopg2.Error as e:
            logger.error(f"Database error generating OTP: {e}", exc_info=True)
            return False, f"OTP generation failed: {str(e)}", None
        except Exception as e:
            logger.error(f"Error generating OTP: {e}", exc_info=True)
            return False, f"OTP generation failed: {str(e)}", None
    
    def verify_signup_otp(self, email: str, otp: str) -> Dict[str, Any]:
        """
        Verify OTP and complete user registration
        
        Args:
            email: User's email
            otp: OTP code to verify
        
        Returns:
            Dictionary with success, message, access_token, user, and expires_in
        """
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get OTP record
            cursor.execute("""
                SELECT email, otp, name, password_hash, password_salt, expires_at, attempts, is_verified
                FROM signup_otps WHERE email = %s
            """, (email.lower(),))
            
            otp_record = cursor.fetchone()
            
            if not otp_record:
                cursor.close()
                conn.close()
                logger.warning(f"[FAILED] OTP verification failed: No OTP found for {email}")
                return {
                    'success': False,
                    'message': "No OTP found for this email"
                }
            
            # Check if OTP has expired
            if datetime.now() > otp_record['expires_at']:
                cursor.close()
                conn.close()
                logger.warning(f"[FAILED] OTP expired for {email}")
                return {
                    'success': False,
                    'message': "OTP has expired"
                }
            
            # Check if max attempts exceeded
            if otp_record['attempts'] >= 3:
                cursor.close()
                conn.close()
                logger.warning(f"[FAILED] OTP verification failed: Max attempts exceeded for {email}")
                return {
                    'success': False,
                    'message': "Maximum OTP verification attempts exceeded"
                }
            
            # Verify OTP
            if otp_record['otp'] != otp:
                # Increment attempts
                cursor.execute("""
                    UPDATE signup_otps SET attempts = attempts + 1 WHERE email = %s
                """, (email.lower(),))
                conn.commit()
                cursor.close()
                conn.close()
                logger.warning(f"[FAILED] OTP verification failed: Invalid OTP for {email}")
                return {
                    'success': False,
                    'message': "Invalid OTP"
                }
            
            # Mark as verified
            cursor.execute("""
                UPDATE signup_otps SET is_verified = true WHERE email = %s
            """, (email.lower(),))
            
            # Create user account
            cursor.execute("""
                INSERT INTO users (name, email, password_hash, password_salt, is_active, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING user_id, name, email, created_at, is_active
            """, (
                otp_record['name'],
                email.lower(),
                otp_record['password_hash'],
                otp_record['password_salt'],
                True,
                datetime.now()
            ))
            
            user_data = cursor.fetchone()
            
            # Delete OTP record
            cursor.execute("DELETE FROM signup_otps WHERE email = %s", (email.lower(),))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            # Create access token
            token_data = {
                "user_id": user_data['user_id'],
                "email": user_data['email']
            }
            access_token = self.jwt_manager.create_access_token(data=token_data)
            
            # Send welcome email if email service is configured
            if self.email_service:
                try:
                    self.email_service.send_welcome_email(
                        user_data['email'],
                        user_data['name']
                    )
                except Exception as e:
                    logger.warning(f"Failed to send welcome email: {e}")
            
            logger.info(f"[SUCCESS] User verified and registered successfully: {email}")
            
            return {
                'success': True,
                'message': "User registered and verified successfully",
                'access_token': access_token,
                'user': {
                    'user_id': user_data['user_id'],
                    'name': user_data['name'],
                    'email': user_data['email'],
                    'created_at': str(user_data['created_at']),
                    'is_active': user_data['is_active']
                },
                'expires_in': self.access_token_expire_minutes * 60
            }
        
        except psycopg2.Error as e:
            logger.error(f"Database error during OTP verification: {e}", exc_info=True)
            return {
                'success': False,
                'message': f"OTP verification failed: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error during OTP verification: {e}", exc_info=True)
            return {
                'success': False,
                'message': f"OTP verification failed: {str(e)}"
            }
    
    def sign_in(self, email: str, password: str) -> Dict[str, Any]:
        """
        Authenticate user with email and password
        
        Args:
            email: User's email address
            password: User's password
        
        Returns:
            Dictionary with success, message, access_token, user, and expires_in
        """
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get user from database
            cursor.execute("""
                SELECT user_id, name, email, password_hash, password_salt, is_active, created_at
                FROM users WHERE email = %s
            """, (email.lower(),))
            
            user = cursor.fetchone()
            
            if not user:
                cursor.close()
                conn.close()
                logger.warning(f"[FAILED] Sign-in failed: User not found for {email}")
                return {
                    'success': False,
                    'message': "Invalid email or password"
                }
            
            # Verify password
            if not self.password_hasher.verify_password(
                password, user['password_hash'], user['password_salt']
            ):
                cursor.close()
                conn.close()
                logger.warning(f"[FAILED] Sign-in failed: Invalid password for {email}")
                return {
                    'success': False,
                    'message': "Invalid email or password"
                }
            
            if not user['is_active']:
                cursor.close()
                conn.close()
                logger.warning(f"[FAILED] Sign-in failed: Account is not active for {email}")
                return {
                    'success': False,
                    'message': "Account is not active"
                }
            
            # Update last login
            cursor.execute("""
                UPDATE users SET last_login = %s WHERE user_id = %s
            """, (datetime.now(), user['user_id']))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            # Create access token
            token_data = {
                "user_id": user['user_id'],
                "email": user['email']
            }
            access_token = self.jwt_manager.create_access_token(data=token_data)
            
            logger.info(f"[SUCCESS] User signed in successfully: {email}")
            
            return {
                'success': True,
                'message': "Sign-in successful",
                'access_token': access_token,
                'user': {
                    'user_id': user['user_id'],
                    'name': user['name'],
                    'email': user['email'],
                    'created_at': str(user['created_at']),
                    'is_active': user['is_active']
                },
                'expires_in': self.access_token_expire_minutes * 60
            }
        
        except psycopg2.Error as e:
            logger.error(f"Database error during sign-in: {e}", exc_info=True)
            return {
                'success': False,
                'message': f"Sign-in failed: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error during sign-in: {e}", exc_info=True)
            return {
                'success': False,
                'message': f"Sign-in failed: {str(e)}"
            }
    
    def request_password_reset(self, email: str) -> Tuple[bool, str, Optional[str]]:
        """
        Generate a password reset token for the user
        
        Args:
            email: User's email address
        
        Returns:
            Tuple of (success, message, encrypted_token)
        """
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Check if user exists
            cursor.execute("SELECT user_id, email, name FROM users WHERE email = %s", (email.lower(),))
            user = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            if not user:
                logger.warning(f"[FAILED] Password reset requested for non-existent user: {email}")
                return False, "If an account exists with this email, a reset link will be sent", None
            
            # Encrypt email in token
            reset_token = encrypt_email(user['email'], self.encryption_key)
            
            # Send password reset email if email service is configured
            if self.email_service:
                try:
                    email_config = self.config.get('email', {})
                    reset_url = email_config.get('reset_password_url', 'http://localhost:3000/reset-password')
                    
                    email_sent = self.email_service.send_password_reset_email(
                        user['email'],
                        user['name'],
                        reset_url_base=reset_url,
                        encrypted_token=reset_token
                    )
                    
                    if email_sent:
                        logger.info(f"✓ Password reset email sent with encrypted token to {email}")
                    else:
                        logger.warning("Failed to send reset email")
                
                except Exception as e:
                    logger.error(f"Failed to send reset email: {e}")
            
            logger.info(f"[SUCCESS] Password reset token generated for: {email}")
            
            return True, "Password reset email sent successfully", reset_token
        
        except Exception as e:
            logger.error(f"Error generating reset token: {e}", exc_info=True)
            return False, f"Error generating reset token: {str(e)}", None
    
    def reset_password_with_token(self, token: str, new_password: str) -> Tuple[bool, str]:
        """
        Reset password using encrypted email token
        
        Args:
            token: Encrypted email token
            new_password: New password
        
        Returns:
            Tuple of (success, message)
        """
        try:
            # Decrypt email from token
            email = decrypt_email(token, self.encryption_key)
            
            if not email:
                logger.warning("[FAILED] Invalid or expired password reset token")
                return False, "Invalid or expired password reset token"
            
            # Reset password using the decrypted email
            return self._reset_password(email, new_password)
        
        except Exception as e:
            logger.error(f"Error during token-based password reset: {e}", exc_info=True)
            return False, f"Password reset failed: {str(e)}"
    
    def _reset_password(self, email: str, new_password: str) -> Tuple[bool, str]:
        """
        Reset user password (internal method)
        
        Args:
            email: User's email address
            new_password: New password
        
        Returns:
            Tuple of (success, message)
        """
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Hash new password
            hashed_password, salt = self.password_hasher.hash_password(new_password)
            
            # Update password
            cursor.execute("""
                UPDATE users
                SET password_hash = %s, password_salt = %s, updated_at = %s
                WHERE email = %s
            """, (hashed_password, salt, datetime.now(), email.lower()))
            
            if cursor.rowcount == 0:
                conn.close()
                logger.warning(f"[FAILED] User not found for password reset: {email}")
                return False, "User not found"
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"[SUCCESS] Password reset successfully for: {email}")
            return True, "Password reset successfully"
        
        except psycopg2.Error as e:
            logger.error(f"Database error during password reset: {e}", exc_info=True)
            return False, f"Password reset failed: {str(e)}"
        except Exception as e:
            logger.error(f"Error during password reset: {e}", exc_info=True)
            return False, f"Password reset failed: {str(e)}"
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify JWT access token
        
        Args:
            token: JWT token to verify
        
        Returns:
            Decoded token data or None if invalid
        """
        return self.jwt_manager.verify_token(token)
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve user information by ID
        
        Args:
            user_id: User ID
        
        Returns:
            Dictionary with user data or None if not found
        """
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT user_id, name, email, created_at, is_active
                FROM users WHERE user_id = %s
            """, (user_id,))
            
            user = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if not user:
                return None
            
            return {
                'user_id': user['user_id'],
                'name': user['name'],
                'email': user['email'],
                'created_at': str(user['created_at']),
                'is_active': user['is_active']
            }
        
        except psycopg2.Error as e:
            logger.error(f"Database error retrieving user: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Error retrieving user: {e}", exc_info=True)
            return None