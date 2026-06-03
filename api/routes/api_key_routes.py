#!/usr/bin/env python3

"""
API Key Management Routes

Handles CRUD operations for API keys:
- Generate new API key for authenticated users
- Retrieve existing API key
- Delete API key
- Validate API key from HTTP headers

Features:
- One API key per user (UNIQUE constraint)
- SHA256 hashing for secure storage
- Fernet encryption for key recovery
- Status tracking (active/inactive)
- Expiration support
"""

import logging
import secrets
import hashlib
import yaml
import os
import re
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pathlib import Path
from cryptography.fernet import Fernet

from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor
import psycopg2

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Router setup
router = APIRouter(prefix="/api-keys", tags=["API Keys"])

# Security scheme for JWT
security = HTTPBearer()

# ==================== CONFIGURATION ====================

def load_config() -> Dict[str, Any]:
    """Load configuration from config.yaml with environment variable substitution"""
    try:
        BASE_DIR = Path(__file__).resolve().parent.parent.parent
        config_path = BASE_DIR / "config.yaml"
        
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(config_path, 'r') as f:
            raw_config = yaml.safe_load(f)
        
        # Substitute environment variables
        config = _substitute_env_vars(raw_config)
        logger.info("Configuration loaded successfully")
        return config
    
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}", exc_info=True)
        raise


def _substitute_env_vars(data):
    """
    Recursively substitute environment variables in configuration.
    Supports format: ${VAR_NAME} or ${VAR_NAME:default_value}
    """
    if isinstance(data, dict):
        return {key: _substitute_env_vars(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    elif isinstance(data, str):
        # Pattern: ${VAR_NAME} or ${VAR_NAME:default_value}
        def replace_var(match):
            var_name = match.group(1)
            default_value = match.group(2)
            return os.getenv(var_name, default_value or "")
        
        return re.sub(r'\$\{([^:}]+)(?::([^}]*))?\}', replace_var, data)
    else:
        return data


# Load config at module level
_CONFIG = load_config()


# ==================== DATABASE UTILITIES ====================

def get_db_connection():
    """
    Create and return a database connection
    
    Returns:
        psycopg2 connection object
    """
    try:
        db_config = _CONFIG.get('postgres', {})
        conn = psycopg2.connect(
            host=db_config.get('host'),
            port=db_config.get('port'),
            database=db_config.get('database'),
            user=db_config.get('user'),
            password=db_config.get('password')
        )
        return conn
    
    except psycopg2.Error as e:
        logger.error(f"Database connection error: {e}", exc_info=True)
        raise


# ==================== ENCRYPTION UTILITIES ====================

def load_encryption_key() -> bytes:
    """Load encryption key from config.yaml"""
    try:
        encryption_key = _CONFIG.get('security', {}).get('encryption_key')
        
        if not encryption_key:
            raise ValueError("encryption_key not found in config.yaml under 'security'")
        
        # Ensure key is bytes
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode()
        
        return encryption_key
    except Exception as e:
        logger.error(f"Error loading encryption key: {e}")
        raise HTTPException(status_code=500, detail="Failed to load encryption configuration")


def generate_api_key(user_id: int) -> str:
    """
    Generate a unique API key using double encryption concept.
    Format: gc-<encrypted_epoch_and_user_id>
    """
    try:
        api_secret_key = os.getenv("API_SECRET_KEY")
        if not api_secret_key:
            raise ValueError("API_SECRET_KEY not found in .env")

        epoch_time = str(int(datetime.utcnow().timestamp()))
        raw_data = f"{epoch_time}_{user_id}"
        
        fernet = Fernet(api_secret_key.encode())
        encrypted_user_api_key = fernet.encrypt(raw_data.encode()).decode()
        
        api_key = f"gc-{encrypted_user_api_key}"
        
        logger.info(f"Generated new API key with prefix: {api_key[:12]}")
        return api_key
    
    except Exception as e:
        logger.error(f"Error generating API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate API key")


def hash_api_key(api_key: str) -> str:
    """Hash API key using SHA256"""
    return hashlib.sha256(api_key.encode()).hexdigest()


def encrypt_api_key(api_key: str, encryption_key: bytes) -> str:
    """Encrypt API key using Fernet"""
    try:
        fernet = Fernet(encryption_key)
        encrypted = fernet.encrypt(api_key.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(f"Error encrypting API key: {e}")
        raise HTTPException(status_code=500, detail="Failed to encrypt API key")


def decrypt_api_key(encrypted_key: str, encryption_key: bytes) -> str:
    """Decrypt API key using Fernet"""
    try:
        fernet = Fernet(encryption_key)
        decrypted = fernet.decrypt(encrypted_key.encode())
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Error decrypting API key: {e}")
        raise HTTPException(status_code=500, detail="Failed to decrypt API key")


# ==================== PYDANTIC MODELS ====================

class ApiKeyResponse(BaseModel):
    """Response model for API key operations"""
    id: int
    user_id: int
    api_key: Optional[str] = Field(None, description="The actual API key (only returned on creation)")
    key_prefix: str = Field(..., description="First 12 characters of the key for identification")
    status: str = Field(..., description="Status of the API key (active/inactive)")
    created_at: str
    updated_at: str
    expires_at: Optional[str] = None


class ApiKeyListResponse(BaseModel):
    """Response model for listing API keys"""
    id: int
    user_id: int
    key_prefix: str
    status: str
    created_at: str
    updated_at: str
    expires_at: Optional[str] = None


class ApiKeyValidationResult(BaseModel):
    """Result of API key validation"""
    valid: bool
    user_id: Optional[int] = None
    api_key_id: Optional[int] = None
    message: str


# ==================== DEPENDENCY FUNCTIONS ====================

def verify_jwt_token(token: str) -> Dict[str, Any]:
    """
    Verify and decode JWT token directly
    
    Args:
        token: JWT token to verify
    
    Returns:
        Decoded token data
    
    Raises:
        HTTPException if token is invalid or expired
    """
    try:
        # Load security config
        security_config = _CONFIG.get('security', {})
        jwt_secret_key = security_config.get('jwt_secret_key')
        jwt_algorithm = security_config.get('jwt_algorithm', 'HS256')
        
        if not jwt_secret_key:
            logger.error("JWT secret key not configured")
            raise HTTPException(status_code=503, detail="Authentication service not initialized")
        
        # Verify and decode token
        payload = jwt.decode(token, jwt_secret_key, algorithms=[jwt_algorithm])
        return payload
    
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"Error verifying JWT token: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail="Failed to verify token")


async def get_current_user_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Extract current user from JWT token
    This is a helper for API key routes
    """
    try:
        token = credentials.credentials
        
        # Verify token directly
        token_data = verify_jwt_token(token)
        
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        user_id = token_data.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token data")
        
        return {'user_id': user_id, 'email': token_data.get('email')}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting user from token: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail="Failed to authenticate user")


# ==================== API KEY ROUTES ====================

@router.post("/generate", response_model=ApiKeyResponse, status_code=201)
async def create_api_key(current_user: Dict[str, Any] = Depends(get_current_user_from_token)):
    """
    Generate a new API key for the authenticated user.
    Only one API key is allowed per user.
    Returns:
        ApiKeyResponse with the generated API key (only shown once)
    Headers:
        Authorization: Bearer <your_jwt_token>
    """
    conn = None
    try:
        user_id = current_user.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found in token")

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check if an API key already exists for the user
        cursor.execute("SELECT id FROM api_keys WHERE user_id = %s LIMIT 1", (user_id,))
        existing_key = cursor.fetchone()
        if existing_key:
            cursor.close()
            conn.close()
            raise HTTPException(
                status_code=400,
                detail="You already have an API key. Please delete your existing API key before generating a new one."
            )

        # Generate new API key using First Level Encryption
        api_key = generate_api_key(user_id)
        key_prefix = api_key[:12]

        # Hash the API key (one-way, for fast authentication lookups)
        key_hash = hash_api_key(api_key)

        # Second Level Encryption for DB Storage
        db_secret_key = os.getenv("DB_SECRET_KEY")
        if not db_secret_key:
            raise ValueError("DB_SECRET_KEY not found in .env")
            
        fernet_db = Fernet(db_secret_key.encode())
        encrypted_key = fernet_db.encrypt(api_key.encode()).decode()

        # Insert new API key
        cursor.execute("""
            INSERT INTO api_keys 
            (user_id, key_hash, encrypted_key, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id, user_id, status, created_at, updated_at, expires_at
        """, (
            user_id,
            key_hash,
            encrypted_key,
            'active'
        ))

        result = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"\u2713 Created API key for user_id: {user_id}")
        logger.info(f"   Key Prefix: {key_prefix}")
        logger.info(f"   Status: active")

        return ApiKeyResponse(
            id=result['id'],
            user_id=result['user_id'],
            api_key=api_key,
            key_prefix=key_prefix,
            status=result['status'],
            created_at=result['created_at'].isoformat(),
            updated_at=result['updated_at'].isoformat(),
            expires_at=result['expires_at'].isoformat() if result['expires_at'] else None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating API key: {e}", exc_info=True)
        if conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to create API key: {str(e)}")


from typing import List

@router.get("/", response_model=List[ApiKeyListResponse])
async def get_api_keys(current_user: Dict[str, Any] = Depends(get_current_user_from_token)):
    """
    Retrieve all API key details for the authenticated user
    Returns:
        List[ApiKeyListResponse] with key details (without the full key)
    Headers:
        Authorization: Bearer <your_jwt_token>
    """
    conn = None
    try:
        user_id = current_user.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found in token")

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT id, user_id, encrypted_key, status, created_at, updated_at, expires_at
            FROM api_keys
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,))

        results = cursor.fetchall()
        cursor.close()
        conn.close()

        if not results:
            return []

        db_secret_key = os.getenv("DB_SECRET_KEY")
        api_keys = []
        for result in results:
            try:
                if not db_secret_key:
                    raise ValueError("DB_SECRET_KEY missing")
                fernet_db = Fernet(db_secret_key.encode())
                decrypted_api_key = fernet_db.decrypt(result['encrypted_key'].encode()).decode()
                key_prefix = decrypted_api_key[:12]
            except Exception:
                key_prefix = "<decryption error>"
            api_keys.append(ApiKeyListResponse(
                id=result['id'],
                user_id=result['user_id'],
                key_prefix=key_prefix,
                status=result['status'],
                created_at=result['created_at'].isoformat(),
                updated_at=result['updated_at'].isoformat(),
                expires_at=result['expires_at'].isoformat() if result['expires_at'] else None
            ))

        logger.info(f"\u2713 Retrieved {len(api_keys)} API key(s) for user_id: {user_id}")
        return api_keys

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving API keys: {e}", exc_info=True)
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to retrieve API keys: {str(e)}")



from fastapi import Query

@router.delete("/", status_code=200)
async def delete_api_key(
    current_user: Dict[str, Any] = Depends(get_current_user_from_token),
    api_key_id: int = Query(None, description="ID of the API key to delete. If not provided, deletes all keys for the user.")
):
    """
    Delete an API key for the authenticated user
    If api_key_id is provided, deletes only that key. If not, deletes all keys for the user.
    Returns:
        Success message
    Headers:
        Authorization: Bearer <your_jwt_token>
    """
    conn = None
    try:
        user_id = current_user.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found in token")

        conn = get_db_connection()
        cursor = conn.cursor()

        if api_key_id is not None:
            # Delete specific API key
            cursor.execute("""
                SELECT id FROM api_keys WHERE user_id = %s AND id = %s
            """, (user_id, api_key_id))
            if not cursor.fetchone():
                cursor.close()
                conn.close()
                raise HTTPException(status_code=404, detail="API key not found for this user or id")
            cursor.execute("""
                DELETE FROM api_keys WHERE user_id = %s AND id = %s
            """, (user_id, api_key_id))
            logger.info(f"\u2713 Deleted API key id={api_key_id} for user_id: {user_id}")
        else:
            # Delete all API keys for user
            cursor.execute("""
                SELECT id FROM api_keys WHERE user_id = %s
            """, (user_id,))
            if not cursor.fetchone():
                cursor.close()
                conn.close()
                raise HTTPException(status_code=404, detail="No API keys found for this user")
            cursor.execute("""
                DELETE FROM api_keys WHERE user_id = %s
            """, (user_id,))
            logger.info(f"\u2713 Deleted ALL API keys for user_id: {user_id}")

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": "API key(s) deleted successfully."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting API key: {e}", exc_info=True)
        if conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to delete API key: {str(e)}")


# ==================== API KEY VALIDATION UTILITY ====================

def validate_api_key_from_header(api_key: str) -> Optional[Dict[str, Any]]:
    """
    Validate API key from Authorization header
    
    Returns:
        Dictionary with user_id and api_key_id if valid, None otherwise
    """
    conn = None
    try:
        # Hash the incoming API key
        key_hash = hash_api_key(api_key)
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Look up the hashed key
        cursor.execute("""
            SELECT id, user_id, status, expires_at
            FROM api_keys
            WHERE key_hash = %s
        """, (key_hash,))
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not result:
            logger.warning("API key not found in database")
            return None
        
        # Check if key is active
        if result['status'] != 'active':
            logger.warning(f"API key is not active. Status: {result['status']}")
            return None
        
        # Check if key is expired
        if result['expires_at']:
            if datetime.utcnow() > result['expires_at']:
                logger.warning("API key has expired")
                return None
        
        logger.info(f"✓ Valid API key for user_id: {result['user_id']}")
        
        return {
            'user_id': result['user_id'],
            'api_key_id': result['id']
        }
    
    except Exception as e:
        logger.error(f"Error validating API key: {e}", exc_info=True)
        if conn:
            conn.close()
        return None


# ==================== API KEY AUTHENTICATION DEPENDENCY ====================

async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    Dependency for verifying API key from X-API-Key header
    
    Usage:
        @app.get("/protected")
        async def protected_endpoint(api_key_user: Dict = Depends(verify_api_key)):
            user_id = api_key_user['user_id']
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="X-API-Key header is required"
        )
    
    validation_result = validate_api_key_from_header(x_api_key)
    
    if not validation_result:
        raise HTTPException(
            status_code=401,
            detail="Invalid, expired, or inactive API key"
        )
    
    return validation_result
