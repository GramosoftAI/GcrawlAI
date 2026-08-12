import base64
import hashlib
import logging
import secrets
from typing import Optional, Tuple
from cryptography.fernet import Fernet

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
