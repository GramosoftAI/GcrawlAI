# Environment Variables Configuration Guide

## Overview
This project uses environment variables stored in a `.env` file to manage sensitive data and configuration. The `.env` file is loaded automatically when the application starts, and variables are substituted into `config.yaml`.

## Setup Instructions

### 1. Create Your .env File
Copy the `.env.example` file to `.env` and fill in your actual values:

```bash
cp .env.example .env
```

Then edit `.env` and replace all placeholder values with your actual credentials:

```env
# PostgreSQL Database Configuration
POSTGRES_HOST=your_db_host
POSTGRES_PORT=5432
POSTGRES_DATABASE=your_db_name
POSTGRES_USER=your_db_user
POSTGRES_PASSWORD=your_secure_password

# Security Configuration
JWT_SECRET_KEY=your_jwt_secret_key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
PASSWORD_RESET_TOKEN_EXPIRE_HOURS=24
ENCRYPTION_KEY=your_encryption_key

# Email Configuration
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USERNAME=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_FROM=noreply@example.com
EMAIL_FROM_NAME=YourAppName
EMAIL_USE_TLS=true
RESET_PASSWORD_URL=https://yourdomain.com/auth/reset_password

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# API Configuration
API_ENV=production
DEBUG=false
```

### 2. Important Security Notes

⚠️ **CRITICAL**: 
- **Never commit `.env` to version control** - It contains sensitive data
- **Always use `.env.example`** as a template for new developers
- **.env.example** can be checked into version control (but with dummy values)
- Keep `.env` file with restricted permissions on production servers

### 3. Variable Format in config.yaml

Variables in `config.yaml` use the following format:

**Format with required variable:**
```yaml
password: "${POSTGRES_PASSWORD}"
```
This will fail if `POSTGRES_PASSWORD` is not defined.

**Format with default value:**
```yaml
host: "${POSTGRES_HOST:localhost}"
```
This will use `POSTGRES_HOST` if defined, otherwise default to `localhost`.

### 4. How It Works

When the application starts:

1. **Load Environment Variables**: The `python-dotenv` package loads all variables from `.env`
2. **Load YAML Config**: The `config.yaml` is loaded
3. **Variable Substitution**: All `${VAR_NAME}` or `${VAR_NAME:default}` patterns are replaced with environment variable values
4. **Use Configuration**: The application uses the resolved configuration

### 5. Environment Variables Reference

#### Database Configuration
| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_HOST` | Yes | PostgreSQL server hostname |
| `POSTGRES_PORT` | No | PostgreSQL server port (default: 5432) |
| `POSTGRES_DATABASE` | Yes | Database name |
| `POSTGRES_USER` | Yes | Database user |
| `POSTGRES_PASSWORD` | Yes | Database password |

#### Security Configuration
| Variable | Required | Description |
|----------|----------|-------------|
| `JWT_SECRET_KEY` | Yes | Secret key for JWT token signing (must be 32+ chars) |
| `JWT_ALGORITHM` | No | JWT algorithm (default: HS256) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Token expiration in minutes (default: 1440) |
| `PASSWORD_RESET_TOKEN_EXPIRE_HOURS` | No | Password reset token expiration (default: 24) |
| `ENCRYPTION_KEY` | Yes | Fernet encryption key for data encryption |

#### Email Configuration
| Variable | Required | Description |
| Variable | Required | Description |
|----------|----------|-------------|
| `EMAIL_HOST` | Yes | SMTP server hostname |
| `EMAIL_PORT` | No | SMTP server port (default: 587) |
| `EMAIL_USERNAME` | Yes | SMTP authentication username |
| `EMAIL_PASSWORD` | Yes | SMTP authentication password |
| `EMAIL_FROM` | Yes | Sender email address |
| `EMAIL_FROM_NAME` | No | Sender display name |
| `EMAIL_USE_TLS` | No | Use TLS encryption (default: true) |
| `RESET_PASSWORD_URL` | No | Password reset URL for email links |

#### Other Configuration
| Variable | Required | Description |
|----------|----------|-------------|
| `REDIS_URL` | No | Redis connection URL |
| `API_ENV` | No | Environment (development/production) |
| `DEBUG` | No | Debug mode (true/false) |

### 6. Generating Secure Keys

#### Generate JWT Secret Key
```python
import secrets
jwt_secret = secrets.token_urlsafe(32)
print(jwt_secret)
```

#### Generate Encryption Key
```python
from cryptography.fernet import Fernet
encryption_key = Fernet.generate_key().decode()
print(encryption_key)
```

### 7. Deployment to Production

For production deployment:

1. **Set environment variables directly** on your server/container instead of using .env file:
   ```bash
   export POSTGRES_PASSWORD="secure_password"
   export JWT_SECRET_KEY="secure_key"
   # ... etc
   ```

2. **Using Docker**: Pass environment variables via `docker run -e`:
   ```bash
   docker run -e POSTGRES_PASSWORD="secure_password" -e JWT_SECRET_KEY="secure_key" your-app
   ```

3. **Using Docker Compose**: Define in `.env` for local development, use secrets for production

### 8. Troubleshooting

**Issue**: Configuration not loading correctly
- Make sure `.env` file exists in the project root
- Verify all required variables are set
- Check for typos in variable names

**Issue**: Database connection failing
- Verify `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD` are correct
- Ensure PostgreSQL server is running
- Test connection manually: `psql -h $POSTGRES_HOST -U $POSTGRES_USER`

**Issue**: Email not sending
- Verify `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USERNAME`, `EMAIL_PASSWORD` are correct
- Check if SMTP server requires TLS/SSL
- Verify sender email address is authorized for SMTP server

## Files Modified

- `.env` - Contains your sensitive data (add to .gitignore)
- `.env.example` - Template file with dummy values (add to git)
- `config.yaml` - Updated to use environment variables
- `api/api.py` - Updated to load environment variables
- `api/auth_manager.py` - Updated to load environment variables
- `api/db_setup.py` - Updated to load environment variables
- `requirements.txt` - Added `python-dotenv` dependency
