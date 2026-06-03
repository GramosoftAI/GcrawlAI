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

# Load environment variables from explicit absolute path
BASE_DIR_PATH = Path(__file__).resolve().parent.parent.parent
dotenv_path = BASE_DIR_PATH / '.env'
load_dotenv(dotenv_path, override=True)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
        
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(create_table_query)
            conn.commit()
            
            cursor.close()
            logger.info("✓ Users table created successfully (or already exists)")
            return True
        
        except psycopg2.Error as e:
            logger.error(f"✗ Failed to create users table: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected error creating users table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()
    
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
        
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(create_table_query)
            conn.commit()
            
            cursor.close()
            logger.info("✓ Signup OTPs table created successfully (or already exists)")
            return True
        
        except psycopg2.Error as e:
            logger.error(f"✗ Failed to create signup_otps table: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected error creating signup_otps table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()
    
    def create_crawl_jobs_table(self) -> bool:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS crawl_jobs (
            id SERIAL PRIMARY KEY,
            crawl_id VARCHAR(64) UNIQUE NOT NULL,
            url TEXT NOT NULL,
            crawl_mode VARCHAR(20) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            SEO BOOLEAN DEFAULT FALSE,
            HTML BOOLEAN DEFAULT FALSE,
            Screenshot BOOLEAN DEFAULT FALSE,
            Markdown BOOLEAN DEFAULT FALSE,
            Images BOOLEAN DEFAULT FALSE,
            links BOOLEAN DEFAULT FALSE,
            user_id VARCHAR(255)
        );

        -- Migration: drop old columns and add links, update user_id type
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='crawl_jobs' AND column_name='task_id') THEN
                ALTER TABLE crawl_jobs DROP COLUMN task_id;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='crawl_jobs' AND column_name='links_file_path') THEN
                ALTER TABLE crawl_jobs DROP COLUMN links_file_path;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='crawl_jobs' AND column_name='summary_file_path') THEN
                ALTER TABLE crawl_jobs DROP COLUMN summary_file_path;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='crawl_jobs' AND column_name='images') THEN
                ALTER TABLE crawl_jobs ADD COLUMN Images BOOLEAN DEFAULT FALSE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='crawl_jobs' AND column_name='links') THEN
                ALTER TABLE crawl_jobs ADD COLUMN links BOOLEAN DEFAULT FALSE;
            END IF;
            ALTER TABLE crawl_jobs DROP CONSTRAINT IF EXISTS fk_crawl_jobs_user;
            ALTER TABLE crawl_jobs ALTER COLUMN user_id TYPE VARCHAR(255);
        END;
        $$;
        """

        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            conn.commit()

            cursor.close()
            logger.info("✓ crawl_jobs table created successfully (or already exists)")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create crawl_jobs table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()



    
    def create_crawl_artifacts_table(self) -> bool:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS crawl_artifacts (
            artifact_id VARCHAR(64) PRIMARY KEY,
            crawl_id VARCHAR(64) NOT NULL,
            page_url TEXT NOT NULL DEFAULT '',
            artifact_type VARCHAR(50) NOT NULL,
            content_kind VARCHAR(20) NOT NULL DEFAULT 'text',
            title TEXT,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_crawl_artifact_job
                FOREIGN KEY (crawl_id)
                REFERENCES crawl_jobs (crawl_id)
                ON DELETE CASCADE,
            CONSTRAINT unique_crawl_artifact
                UNIQUE (crawl_id, page_url, artifact_type)
        );

        CREATE INDEX IF NOT EXISTS idx_crawl_artifacts_crawl_id
            ON crawl_artifacts(crawl_id);
        CREATE INDEX IF NOT EXISTS idx_crawl_artifacts_page_url
            ON crawl_artifacts(crawl_id, page_url);
        """

        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            conn.commit()

            cursor.close()
            logger.info("✓ crawl_artifacts table created successfully (or already exists)")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create crawl_artifacts table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()



    def create_reported_issues_table(self) -> bool:
        """
        Create reported_issues table if it doesn't exist.
        Stores user-submitted issue reports with affected URL,
        issue categories, and a free-text explanation.
        """
        create_table_query = """
        CREATE TABLE IF NOT EXISTS reported_issues (
            id SERIAL PRIMARY KEY,
            url_affected TEXT NOT NULL,
            issue_related_to TEXT[] NOT NULL,
            explanation TEXT NOT NULL,
            email TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        -- Migrate existing tables: add email column if it doesn't exist
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'reported_issues' AND column_name = 'email'
            ) THEN
                ALTER TABLE reported_issues ADD COLUMN email TEXT;
            END IF;
        END;
        $$;

        CREATE INDEX IF NOT EXISTS idx_reported_issues_created_at ON reported_issues(created_at);
        """

        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            conn.commit()

            cursor.close()
            logger.info("✓ reported_issues table created successfully (or already exists)")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create reported_issues table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def create_api_keys_table(self) -> bool:
        """
        Create api_keys table if it doesn't exist.
        Stores API keys for users with hashed and encrypted versions.
        """
        create_table_query = """
        CREATE TABLE IF NOT EXISTS api_keys (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
            key_hash VARCHAR(64) NOT NULL,
            encrypted_key TEXT NOT NULL,
            status VARCHAR(20) DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            UNIQUE(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
        CREATE INDEX IF NOT EXISTS idx_api_keys_status ON api_keys(status);
        """

        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            conn.commit()

            cursor.close()
            logger.info("✓ api_keys table created successfully (or already exists)")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create api_keys table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def create_crawl_errors_table(self) -> bool:
        """
        Create crawl_errors table if it doesn't exist.
        Stores errors related to crawling failures (e.g., screenshots, blocking).
        """
        create_table_query = """
        CREATE TABLE IF NOT EXISTS crawl_errors (
            id SERIAL PRIMARY KEY,
            crawl_id VARCHAR(64),
            url TEXT,
            error_source VARCHAR(50), -- screenshot, image, seo, links, markdown, html, json
            reason TEXT,
            blocked_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            user_id VARCHAR(255),
            CONSTRAINT fk_crawl_errors_job
                FOREIGN KEY (crawl_id)
                REFERENCES crawl_jobs (crawl_id)
                ON DELETE CASCADE
        );
        
        -- Migration: Add user_id to crawl_errors
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='crawl_errors' AND column_name='user_id') THEN
                ALTER TABLE crawl_errors ADD COLUMN user_id VARCHAR(255);
            END IF;
        END;
        $$;

        CREATE INDEX IF NOT EXISTS idx_crawl_errors_crawl_id ON crawl_errors(crawl_id);
        CREATE INDEX IF NOT EXISTS idx_crawl_errors_created_at ON crawl_errors(created_at);
        """

        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            conn.commit()

            cursor.close()
            logger.info("✓ crawl_errors table created successfully (or already exists)")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create crawl_errors table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def create_activity_logs_table(self) -> bool:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS activity_logs (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL,
            job_id VARCHAR(64),
            endpoint VARCHAR(100) NOT NULL,
            url TEXT NOT NULL,
            status VARCHAR(50) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Migration: drop constraint and alter type, add/rename job_id
        DO $$
        BEGIN
            ALTER TABLE activity_logs DROP CONSTRAINT IF EXISTS fk_activity_logs_user;
            ALTER TABLE activity_logs ALTER COLUMN user_id TYPE VARCHAR(255);
            
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='activity_logs' AND column_name='request_id') THEN
                ALTER TABLE activity_logs RENAME COLUMN request_id TO job_id;
            ELSIF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='activity_logs' AND column_name='job_id') THEN
                ALTER TABLE activity_logs ADD COLUMN job_id VARCHAR(64);
            END IF;
        END;
        $$;
        CREATE INDEX IF NOT EXISTS idx_activity_logs_user_id ON activity_logs(user_id);
        CREATE INDEX IF NOT EXISTS idx_activity_logs_created_at ON activity_logs(created_at DESC);
        """

        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            conn.commit()

            cursor.close()
            logger.info("✓ activity_logs table created successfully (or already exists)")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create activity_logs table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def create_job_results_table(self) -> bool:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS job_results (
            job_id VARCHAR(64) NOT NULL,
            user_id VARCHAR(255),
            json_content JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (job_id, created_at)
        ) PARTITION BY RANGE (created_at);
        """
        
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            
            # Create partitions for current day and next 7 days
            import datetime
            for i in range(-2, 10):
                d = (datetime.datetime.now() + datetime.timedelta(days=i)).date()
                d_next = d + datetime.timedelta(days=1)
                part_name = f"job_results_{d.strftime('%Y_%m_%d')}"
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {part_name} PARTITION OF job_results 
                    FOR VALUES FROM ('{d.strftime('%Y-%m-%d')}') TO ('{d_next.strftime('%Y-%m-%d')}')
                """)
                cursor.execute(f"""
                    ALTER TABLE {part_name} SET (
                        autovacuum_vacuum_scale_factor = 0.01,
                        autovacuum_analyze_scale_factor = 0.01,
                        autovacuum_vacuum_cost_delay = 2,
                        autovacuum_vacuum_threshold = 50
                    )
                """)
                
            conn.commit()
            cursor.close()
            logger.info("✓ job_results table and partitions created successfully")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create job_results table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def create_search_jobs_table(self) -> bool:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS search_jobs (
            id SERIAL PRIMARY KEY,
            search_id VARCHAR(64) UNIQUE NOT NULL,
            query TEXT NOT NULL,
            "limit" INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            user_id VARCHAR(255)
        );
        
        -- Migration: add user_id column if missing, drop constraint
        DO $$
        BEGIN
            ALTER TABLE search_jobs DROP CONSTRAINT IF EXISTS fk_search_jobs_user;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='search_jobs' AND column_name='user_id') THEN
                ALTER TABLE search_jobs ADD COLUMN user_id VARCHAR(255);
            ELSE
                ALTER TABLE search_jobs ALTER COLUMN user_id TYPE VARCHAR(255);
            END IF;
        END;
        $$;
        
        CREATE INDEX IF NOT EXISTS idx_search_jobs_search_id ON search_jobs(search_id);
        """

        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            conn.commit()

            cursor.close()
            logger.info("✓ search_jobs table created successfully (or already exists)")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create search_jobs table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def create_search_errors_table(self) -> bool:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS search_errors (
            id SERIAL PRIMARY KEY,
            search_id VARCHAR(64),
            query TEXT,
            error_source VARCHAR(50),
            reason TEXT,
            blocked_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            user_id VARCHAR(255)
        );
        
        -- Migration: add user_id to search_errors
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='search_errors' AND column_name='user_id') THEN
                ALTER TABLE search_errors ADD COLUMN user_id VARCHAR(255);
            END IF;
        END;
        $$;
        CREATE INDEX IF NOT EXISTS idx_search_errors_search_id ON search_errors(search_id);
        CREATE INDEX IF NOT EXISTS idx_search_errors_created_at ON search_errors(created_at);
        """

        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute(create_table_query)
            conn.commit()

            cursor.close()
            logger.info("✓ search_errors table created successfully (or already exists)")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to create search_errors table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute(create_table_query)
            conn.commit()
            cursor.close()
            logger.info("✓ activity_logs table created successfully")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to create activity_logs table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def setup_all_tables(self) -> bool:
        logger.info("Starting database setup...")

        users_created = self.create_users_table()
        otps_created = self.create_signup_otps_table()
        api_keys_created = self.create_api_keys_table()
        crawl_jobs_created = self.create_crawl_jobs_table()
        search_jobs_created = self.create_search_jobs_table()
        crawl_artifacts_created = self.create_crawl_artifacts_table()
        reported_issues_created = self.create_reported_issues_table()
        crawl_errors_created = self.create_crawl_errors_table()
        search_errors_created = self.create_search_errors_table()
        activity_logs_created = self.create_activity_logs_table()
        job_results_created = self.create_job_results_table()

        if all([users_created, otps_created, api_keys_created, crawl_jobs_created, search_jobs_created,
                crawl_artifacts_created, reported_issues_created, crawl_errors_created, search_errors_created, activity_logs_created, job_results_created]):
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
        
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(verify_query)
            tables = cursor.fetchall()
            
            cursor.close()
            
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
        finally:
            if conn:
                conn.close()
    
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
        
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute(drop_query)
            conn.commit()
            
            cursor.close()
            
            logger.warning("⚠ All authentication tables dropped")
            return True
        
        except psycopg2.Error as e:
            logger.error(f"✗ Failed to drop tables: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected error dropping tables: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()


def main():
    """Main execution function"""
    try:
        # Get project root (two levels up from api/core/)
        BASE_DIR = Path(__file__).resolve().parent.parent.parent
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