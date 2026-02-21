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
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_path = os.path.join(BASE_DIR, "config.yaml")


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DatabaseSetup:
    """Handles database initialization and table creation"""
    
    def __init__(self, config_path: str = config_path):
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
            return {key: DatabaseSetup._substitute_env_vars(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [DatabaseSetup._substitute_env_vars(item) for item in data]
        elif isinstance(data, str):
            # Pattern: ${VAR_NAME} or ${VAR_NAME:default_value}
            def replace_var(match):
                var_name = match.group(1)
                default_value = match.group(2)
                return os.getenv(var_name, default_value or "")
            
            return re.sub(r'\$\{([^:}]+)(?::([^}]*))?\}', replace_var, data)
        else:
            return data
    
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
    
    def create_crawl_jobs_table(self) -> bool:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS crawl_jobs (
            id SERIAL PRIMARY KEY,
            crawl_id VARCHAR(64) UNIQUE NOT NULL,
            url TEXT NOT NULL,
            crawl_mode VARCHAR(20) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            task_id VARCHAR(255),
            SEO BOOLEAN DEFAULT FALSE,
            HTML BOOLEAN DEFAULT FALSE,
            Screenshot BOOLEAN DEFAULT FALSE,
            Markdown BOOLEAN DEFAULT FALSE
        );
        """

        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            conn.commit()

            cursor.close()
            conn.close()

            logger.info("✓ crawl_jobs table created successfully (or already exists)")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create crawl_jobs table: {e}", exc_info=True)
            return False

    def create_crawl_events_table(self) -> bool:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS crawl_events (
            id SERIAL PRIMARY KEY,
            crawl_id VARCHAR(64) NOT NULL,
            event_type VARCHAR(50) NOT NULL,
            url TEXT,
            title TEXT,
            markdown_file TEXT,
            html_file TEXT,
            screenshot TEXT,
            seo_json TEXT,
            seo_md TEXT,
            seo_xlsx TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_crawl_job
                FOREIGN KEY (crawl_id)
                REFERENCES crawl_jobs (crawl_id)
                ON DELETE CASCADE,
            CONSTRAINT unique_crawl_file 
                UNIQUE (crawl_id, markdown_file)
        );
        
        CREATE INDEX IF NOT EXISTS idx_crawl_events_crawl_id ON crawl_events(crawl_id);
        """

        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            conn.commit()

            cursor.close()
            conn.close()

            logger.info("✓ crawl_events table created successfully (or already exists)")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create crawl_events table: {e}", exc_info=True)
            return False


    def create_crawls_table(self) -> bool:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS crawls (
            id SERIAL PRIMARY KEY,
            crawl_id VARCHAR(64) UNIQUE NOT NULL,
            url TEXT NOT NULL,
            markdown_path TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER,
            CONSTRAINT fk_crawls_user
                FOREIGN KEY (user_id)
                REFERENCES users (user_id)
                ON DELETE CASCADE
        );
        """

        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            conn.commit()

            cursor.close()
            conn.close()

            logger.info("✓ crawls table created successfully (or already exists)")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create crawls table: {e}", exc_info=True)
            return False

    
    def setup_all_tables(self) -> bool:
        logger.info("Starting database setup...")

        users_created = self.create_users_table()
        otps_created = self.create_signup_otps_table()
        crawl_jobs_created = self.create_crawl_jobs_table()
        crawl_events_created = self.create_crawl_events_table()
        crawls_created = self.create_crawls_table()

        if all([users_created, otps_created, crawl_jobs_created, crawl_events_created, crawls_created]):
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
        # Get project root (one level up from api/)
        BASE_DIR = Path(__file__).resolve().parent.parent
        config_path = BASE_DIR / "config.yaml"

        db_setup = DatabaseSetup(str(config_path))
        
        # Create all tables
        success = db_setup.setup_all_tables()
        
        if success:
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