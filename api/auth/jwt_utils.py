import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import jwt

logger = logging.getLogger(__name__)

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
