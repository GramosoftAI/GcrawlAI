#!/usr/bin/env python3

"""
Database Setup for Authentication System

Creates PostgreSQL database tables for user authentication and OTP verification.
Reads database credentials from config.yaml and creates tables with proper constraints.
"""

import logging
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import yaml
from pathlib import Path
from typing import Dict, Any
import os


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DatabaseSetup:
    """Handles database initialization and table creation"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize database setup
        
        Args:
            config_path: Path to configuration file
        """
        self.config = self._load_config(config_path)
        self.db_config = self.config.get('postgres', {})
        
        if not self.db_config:
            raise ValueError("PostgreSQL configuration not found in config.yaml")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """
        Load configuration from YAML file
        
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
                config = yaml.safe_load(f)
            
            logger.info(f"Configuration loaded from {config_path}")
            return config
        
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}", exc_info=True)
            raise
    
    def _get_db_connection(self, autocommit: bool = False):
        """
        Create and return a database connection
        
        Args:
            autocommit: Whether to enable autocommit mode
            
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
            
            if autocommit:
                conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            
            return conn
        
        except psycopg2.Error as e:
            logger.error(f"Database connection error: {e}", exc_info=True)
            raise
    
    def create_users_table(self) -> bool:
        """
        Create users table if it doesn't exist
        
        Returns:
            True if table created or already exists, False on error
        """
        create_table_query = """
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
        """
        
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(create_table_query)
            conn.commit()
            
            cursor.close()
            conn.close()
            
            logger.info("✓ Users table created successfully (or already exists)")
            return True
        
        except psycopg2.Error as e:
            logger.error(f"✗ Failed to create users table: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected error creating users table: {e}", exc_info=True)
            return False
    
    def create_signup_otps_table(self) -> bool:
        """
        Create signup_otps table if it doesn't exist
        
        Returns:
            True if table created or already exists, False on error
        """
        create_table_query = """
        CREATE TABLE IF NOT EXISTS signup_otps (
            email VARCHAR(255) PRIMARY KEY,
            otp VARCHAR(5) NOT NULL,
            name VARCHAR(255) NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            attempts INTEGER DEFAULT 0,
            is_verified BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_signup_otps_expires_at ON signup_otps(expires_at);
        CREATE INDEX IF NOT EXISTS idx_signup_otps_is_verified ON signup_otps(is_verified);
        """
        
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(create_table_query)
            conn.commit()
            
            cursor.close()
            conn.close()
            
            logger.info("✓ Signup OTPs table created successfully (or already exists)")
            return True
        
        except psycopg2.Error as e:
            logger.error(f"✗ Failed to create signup_otps table: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected error creating signup_otps table: {e}", exc_info=True)
            return False
    
    def setup_all_tables(self) -> bool:
        """
        Create all required database tables
        
        Returns:
            True if all tables created successfully, False otherwise
        """
        logger.info("Starting database setup...")
        
        users_created = self.create_users_table()
        otps_created = self.create_signup_otps_table()
        
        if users_created and otps_created:
            logger.info("✓ Database setup completed successfully")
            return True
        else:
            logger.error("✗ Database setup failed")
            return False
    
    def verify_tables_exist(self) -> bool:
        """
        Verify that all required tables exist
        
        Returns:
            True if all tables exist, False otherwise
        """
        verify_query = """
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name IN ('users', 'signup_otps');
        """
        
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(verify_query)
            tables = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            table_names = [table[0] for table in tables]
            
            required_tables = ['users', 'signup_otps']
            all_exist = all(table in table_names for table in required_tables)
            
            if all_exist:
                logger.info("✓ All required tables exist")
                logger.info(f"  Tables found: {', '.join(table_names)}")
            else:
                missing = [t for t in required_tables if t not in table_names]
                logger.warning(f"✗ Missing tables: {', '.join(missing)}")
            
            return all_exist
        
        except psycopg2.Error as e:
            logger.error(f"✗ Failed to verify tables: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected error verifying tables: {e}", exc_info=True)
            return False
    
    def drop_all_tables(self) -> bool:
        """
        Drop all authentication tables (USE WITH CAUTION)
        
        Returns:
            True if tables dropped successfully, False otherwise
        """
        drop_query = """
        DROP TABLE IF EXISTS signup_otps CASCADE;
        DROP TABLE IF EXISTS users CASCADE;
        """
        
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(drop_query)
            conn.commit()
            
            cursor.close()
            conn.close()
            
            logger.warning("⚠ All authentication tables dropped")
            return True
        
        except psycopg2.Error as e:
            logger.error(f"✗ Failed to drop tables: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected error dropping tables: {e}", exc_info=True)
            return False


def main():
    """Main execution function"""
    try:
        # db_setup = DatabaseSetup("config.yaml")

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(BASE_DIR, "config.yaml")
        db_setup = DatabaseSetup(config_path)
        
        # Create all tables
        success = db_setup.setup_all_tables()
        
        if success:
            # Verify tables were created
            db_setup.verify_tables_exist()
            logger.info("\n" + "="*50)
            logger.info("Database setup completed successfully!")
            logger.info("="*50)
        else:
            logger.error("\n" + "="*50)
            logger.error("Database setup failed!")
            logger.error("="*50)
            return False
        
        return True
    
    except Exception as e:
        logger.error(f"Database setup error: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)