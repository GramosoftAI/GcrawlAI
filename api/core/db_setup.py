#!/usr/bin/env python3
"""
Database Setup for GcrawlAI Authentication and Crawl System
Creates PostgreSQL database tables, triggers partitions, and populates ISP tables.
"""

import logging
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
import os
import re
import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

# Load environment variables
BASE_DIR_PATH = Path(__file__).resolve().parent.parent.parent
dotenv_path = BASE_DIR_PATH / '.env'
load_dotenv(dotenv_path, override=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Fallback ISP priority list
PRIORITY_ISPS = ["jio", "airtel", "reliance", "vodafone", "idea", "bsnl", "comcast", "spectrum", "at&t"]


class DatabaseSetup:
    """Handles PostgreSQL database initialization, table creation, partitioning, and seeding"""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize database setup configurations"""
        self.config = {}
        self.db_config = {}
        
        if not config_path:
            config_path = str(BASE_DIR_PATH / "config.yaml")

        if os.path.exists(config_path):
            self.config = self._load_config(config_path)
            self.db_config = self.config.get('postgres', {})

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file with environment variable substitution"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                raw_config = yaml.safe_load(f)
            return self._substitute_env_vars(raw_config)
        except Exception as e:
            logger.warning(f"Could not load config.yaml: {e}. Falling back exclusively to environment variables.")
            return {}

    @staticmethod
    def _substitute_env_vars(data):
        """Recursively substitute environment variables in configuration"""
        if isinstance(data, dict):
            return {key: DatabaseSetup._substitute_env_vars(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [DatabaseSetup._substitute_env_vars(item) for item in data]
        elif isinstance(data, str):
            def replace_var(match):
                """Replace var."""
                var_name = match.group(1)
                default_value = match.group(2)
                return os.getenv(var_name, default_value or "")
            return re.sub(r'\$\{([^:}]+)(?::([^}]*))?\}', replace_var, data)
        else:
            return data

    def _get_db_connection(self):
        """Create and return a database connection, prioritizing environment variables"""
        host = os.getenv("POSTGRES_HOST")
        port = os.getenv("POSTGRES_PORT")
        database = os.getenv("POSTGRES_DATABASE")
        user = os.getenv("POSTGRES_USER")
        password = os.getenv("POSTGRES_PASSWORD")

        # Fallback to config.yaml if environment variables are missing
        if not all([host, port, database, user, password]) and self.db_config:
            host = host or self.db_config.get("host")
            port = port or self.db_config.get("port")
            database = database or self.db_config.get("database")
            user = user or self.db_config.get("user")
            password = password or self.db_config.get("password")

        # Set standard defaults
        host = host
        port = port
        database = database
        user = user
        password = password

        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute("SET TIME ZONE 'Asia/Kolkata';")
            conn.commit()
        except Exception as e:
            logger.warning(f"Failed to set session timezone to Asia/Kolkata: {e}")
        return conn

    def execute_query(self, query: str, params: Optional[tuple] = None, commit: bool = True) -> bool:
        """Helper to safely execute a SQL query"""
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            if commit:
                conn.commit()
            cursor.close()
            return True
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"SQL execution error: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def create_users_table(self) -> bool:
        """Create users table and corresponding indexes"""
        query = """
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            admin_login BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
        """
        return self.execute_query(query)

    def create_signup_otps_table(self) -> bool:
        """Create signup_otps table and indexes"""
        query = """
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
        return self.execute_query(query)

    def create_crawl_jobs_table(self) -> bool:
        """Create crawl_jobs table"""
        query = """
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
        """
        return self.execute_query(query)


    def create_reported_issues_table(self) -> bool:
        """Create reported_issues table and index"""
        query = """
        CREATE TABLE IF NOT EXISTS reported_issues (
            id SERIAL PRIMARY KEY,
            url_affected TEXT NOT NULL,
            issue_related_to TEXT[] NOT NULL,
            explanation TEXT NOT NULL,
            email TEXT NOT NULL,
            user_id VARCHAR(255),
            status VARCHAR(50) NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_reported_issues_created_at ON reported_issues(created_at);
        """
        success = self.execute_query(query)
        if success:
            conn = None
            try:
                conn = self._get_db_connection()
                cursor = conn.cursor()
                cursor.execute("ALTER TABLE reported_issues ADD COLUMN IF NOT EXISTS user_id VARCHAR(255);")
                cursor.execute("ALTER TABLE reported_issues ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'Pending';")
                cursor.execute("ALTER TABLE reported_issues ALTER COLUMN email SET NOT NULL;")
                conn.commit()
                cursor.close()
            except Exception as e:
                logger.warning(f"Failed to run migration query for reported_issues table: {e}")
            finally:
                if conn:
                    conn.close()
        return success

    def create_admin_emails_table(self) -> bool:
        """Create admin_emails table and index"""
        query = """
        CREATE TABLE IF NOT EXISTS admin_emails (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_admin_emails_email ON admin_emails(email);
        """
        return self.execute_query(query)

    def create_api_keys_table(self) -> bool:
        """Create api_keys table and indexes"""
        query = """
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
        return self.execute_query(query)

    def create_crawl_errors_table(self) -> bool:
        """Create crawl_errors table and indexes"""
        query = """
        CREATE TABLE IF NOT EXISTS crawl_errors (
            id SERIAL PRIMARY KEY,
            crawl_id VARCHAR(64),
            url TEXT,
            error_source VARCHAR(50), 
            reason TEXT,
            blocked_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            user_id VARCHAR(255),
            CONSTRAINT fk_crawl_errors_job
                FOREIGN KEY (crawl_id)
                REFERENCES crawl_jobs (crawl_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_crawl_errors_crawl_id ON crawl_errors(crawl_id);
        CREATE INDEX IF NOT EXISTS idx_crawl_errors_created_at ON crawl_errors(created_at);
        """
        return self.execute_query(query)

    def create_activity_logs_table(self) -> bool:
        """Create activity_logs table and indexes"""
        query = """
        CREATE TABLE IF NOT EXISTS activity_logs (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL,
            job_id VARCHAR(64),
            endpoint VARCHAR(100) NOT NULL,
            url TEXT NOT NULL,
            status VARCHAR(50) NOT NULL,
            time_taken VARCHAR(50),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_activity_logs_user_id ON activity_logs(user_id);
        CREATE INDEX IF NOT EXISTS idx_activity_logs_created_at ON activity_logs(created_at DESC);
        """
        return self.execute_query(query)

    def create_admin_error_logs_table(self) -> bool:
        """Create admin_error_logs table and indexes"""
        query = """
        CREATE TABLE IF NOT EXISTS admin_error_logs (
            id SERIAL PRIMARY KEY,
            log_id VARCHAR(64) NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_tool VARCHAR(50) NOT NULL,
            target_domain TEXT NOT NULL,
            error_type VARCHAR(100) NOT NULL,
            severity VARCHAR(50) NOT NULL,
            proxy_ip TEXT,
            error_details TEXT,
            request_params JSONB,
            stack_trace TEXT,
            user_id VARCHAR(255)
        );
        CREATE INDEX IF NOT EXISTS idx_admin_error_logs_log_id ON admin_error_logs(log_id);
        CREATE INDEX IF NOT EXISTS idx_admin_error_logs_created_at ON admin_error_logs(timestamp DESC);
        """
        return self.execute_query(query)

    def create_job_results_table(self) -> bool:
        """Create job_results table (partitioned by range on created_at) and daily partition shards"""
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
            
            # Pre-create daily partitions for yesterday, today, and the next 10 days
            try:
                for i in range(-2, 11):
                    d = (datetime.datetime.now() + datetime.timedelta(days=i)).date()
                    d_next = d + datetime.timedelta(days=1)
                    part_name = f"job_results_{d.strftime('%Y_%m_%d')}"
                    
                    cursor.execute(f"""
                        CREATE TABLE IF NOT EXISTS {part_name} PARTITION OF job_results 
                        FOR VALUES FROM ('{d.strftime('%Y-%m-%d')} 00:00:00+05:30') TO ('{d_next.strftime('%Y-%m-%d')} 00:00:00+05:30')
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
            except Exception as partition_err:
                conn.rollback()
                logger.warning(f"⚠ Partition creation failed ({partition_err}). Dropping job_results table to re-align timezone partitions...")
                cursor.execute("DROP TABLE IF EXISTS job_results CASCADE;")
                conn.commit()
                
                # Re-create table and retry partition registration
                cursor.execute(create_table_query)
                for i in range(-2, 11):
                    d = (datetime.datetime.now() + datetime.timedelta(days=i)).date()
                    d_next = d + datetime.timedelta(days=1)
                    part_name = f"job_results_{d.strftime('%Y_%m_%d')}"
                    
                    cursor.execute(f"""
                        CREATE TABLE IF NOT EXISTS {part_name} PARTITION OF job_results 
                        FOR VALUES FROM ('{d.strftime('%Y-%m-%d')} 00:00:00+05:30') TO ('{d_next.strftime('%Y-%m-%d')} 00:00:00+05:30')
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
                logger.info("✓ Re-created partitioned job_results table and partitions successfully after timezone alignment.")
                
            cursor.close()
            return True
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"✗ Failed to create partitioned job_results table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def create_search_jobs_table(self) -> bool:
        """Create search_jobs table and indexes"""
        query = """
        CREATE TABLE IF NOT EXISTS search_jobs (
            id SERIAL PRIMARY KEY,
            search_id VARCHAR(64) UNIQUE NOT NULL,
            query TEXT NOT NULL,
            "limit" INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            user_id VARCHAR(255)
        );
        CREATE INDEX IF NOT EXISTS idx_search_jobs_search_id ON search_jobs(search_id);
        """
        return self.execute_query(query)

    def create_search_errors_table(self) -> bool:
        """Create search_errors table and indexes"""
        query = """
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
        CREATE INDEX IF NOT EXISTS idx_search_errors_search_id ON search_errors(search_id);
        CREATE INDEX IF NOT EXISTS idx_search_errors_created_at ON search_errors(created_at);
        """
        return self.execute_query(query)

    def create_api_endpoints_table(self) -> bool:
        """Create api_endpoints table and seed default endpoint rows"""
        create_table_query = """
        CREATE TABLE IF NOT EXISTS api_endpoints (
            id SERIAL PRIMARY KEY,
            endpoint_name VARCHAR(100) UNIQUE NOT NULL,
            url_path VARCHAR(255) NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'Active',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        seed_query = """
        INSERT INTO api_endpoints (endpoint_name, url_path, status, is_active)
        VALUES 
            ('Scrape API', '/v1/scrape', 'Active', true),
            ('Crawl API', '/v1/crawl', 'Active', true),
            ('Links API', '/v1/links', 'Active', true),
            ('Screenshot API', '/v1/screenshot', 'Active', true),
            ('Search API', '/v1/search', 'Active', true)
        ON CONFLICT (endpoint_name) DO NOTHING;
        """
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute(create_table_query)
            cursor.execute(seed_query)
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"✗ Failed to create/seed api_endpoints: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def create_subscription_plans_tables(self) -> bool:
        """Create monthly and yearly subscription plans tables and seed default pricing plans"""
        drop_old_query = """
        DROP TABLE IF EXISTS subscription_plans CASCADE;
        DROP TABLE IF EXISTS monthly_subscription_plans CASCADE;
        DROP TABLE IF EXISTS yearly_subscription_plans CASCADE;
        """

        create_monthly_query = """
        CREATE TABLE IF NOT EXISTS monthly_subscription_plans (
            id SERIAL PRIMARY KEY,
            plan_name VARCHAR(100) UNIQUE NOT NULL,
            plan_key VARCHAR(100) UNIQUE NOT NULL,
            price VARCHAR(100) NOT NULL,
            credits_included INTEGER NOT NULL,
            max_concurrency INTEGER NOT NULL,
            monthly_product_id VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        create_yearly_query = """
        CREATE TABLE IF NOT EXISTS yearly_subscription_plans (
            id SERIAL PRIMARY KEY,
            plan_name VARCHAR(100) UNIQUE NOT NULL,
            plan_key VARCHAR(100) UNIQUE NOT NULL,
            price VARCHAR(100) NOT NULL,
            credits_included INTEGER NOT NULL,
            max_concurrency INTEGER NOT NULL,
            yearly_product_id VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        seed_monthly_query = """
        INSERT INTO monthly_subscription_plans (plan_name, plan_key, price, credits_included, max_concurrency)
        VALUES 
            ('Free', 'free', '$0/mo', 500, 2),
            ('Starter', 'starter', '$19/mo', 3000, 5),
            ('Growth', 'growth', '$29/mo', 50000, 15),
            ('Pro', 'pro', '$49/mo', 150000, 25)
        ON CONFLICT (plan_key) DO NOTHING;
        """
        
        seed_yearly_query = """
        INSERT INTO yearly_subscription_plans (plan_name, plan_key, price, credits_included, max_concurrency)
        VALUES 
            ('Free', 'free', '$0/yr', 500, 2),
            ('Starter', 'starter', '$190/yr', 36000, 5),
            ('Growth', 'growth', '$290/yr', 600000, 15),
            ('Pro', 'pro', '$490/yr', 1800000, 25)
        ON CONFLICT (plan_key) DO NOTHING;
        """
        
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute(drop_old_query)
            cursor.execute(create_monthly_query)
            cursor.execute(create_yearly_query)
            cursor.execute(seed_monthly_query)
            cursor.execute(seed_yearly_query)
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"✗ Failed to create/seed monthly/yearly subscription plans: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()
    def create_custom_requests_table(self) -> bool:
        """Create custom_requests table for storing public custom scraping requests"""
        query = """
        CREATE TABLE IF NOT EXISTS custom_requests (
            id SERIAL PRIMARY KEY,
            full_name VARCHAR(255) NOT NULL,
            work_email VARCHAR(255) NOT NULL,
            company VARCHAR(255),
            expected_volume VARCHAR(100) NOT NULL,
            request_type VARCHAR(100) NOT NULL,
            target_websites TEXT NOT NULL,
            description TEXT NOT NULL,
            status VARCHAR(50) DEFAULT 'New',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute(query)
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"✗ Failed to create custom_requests table: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()


    def create_payment_tables(self) -> bool:
        """Create billing and plans tables (user_plans, payment_requests, plan_expiry, subscriptions)"""
        queries = [
            """
            CREATE TABLE IF NOT EXISTS user_plans (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                plan_type VARCHAR(50) NOT NULL DEFAULT 'free',
                used_requests BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS rollover_credits (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                credits BIGINT NOT NULL,
                expiry_date TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS payment_requests (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                plan_type VARCHAR(50) NOT NULL,
                subscript_type VARCHAR(50) NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                currency VARCHAR(10) NOT NULL DEFAULT 'USD',
                stripe_payment_id VARCHAR(255),
                status VARCHAR(50) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS plan_expiry (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                plan_type VARCHAR(50) NOT NULL,
                subscript_type VARCHAR(50) NOT NULL,
                expiry_date TIMESTAMP WITH TIME ZONE NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                stripe_customer_id VARCHAR(255),
                stripe_subscription_id VARCHAR(255),
                plan_type VARCHAR(50) NOT NULL,
                subscript_type VARCHAR(50) NOT NULL,
                status VARCHAR(50) NOT NULL,
                current_period_start TIMESTAMP WITH TIME ZONE NOT NULL,
                current_period_end TIMESTAMP WITH TIME ZONE NOT NULL,
                cancelled_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """
        ]
        
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            for q in queries:
                cursor.execute(q)
            
            # Drop obsolete columns from user_plans if they exist
            cursor.execute("ALTER TABLE user_plans DROP COLUMN IF EXISTS total_requests;")
            cursor.execute("ALTER TABLE user_plans DROP COLUMN IF EXISTS concurrency_limit;")
            
            conn.commit()
            
            # Post-check: ensure all existing users are assigned a free plan limits entry
            cursor.execute("SELECT user_id FROM users;")
            users = cursor.fetchall()
            for u in users:
                uid = u[0]
                cursor.execute("SELECT id FROM user_plans WHERE user_id = %s", (uid,))
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO user_plans (user_id, plan_type, used_requests)
                        VALUES (%s, 'free', 0)
                    """, (uid,))
                    cursor.execute("""
                        INSERT INTO plan_expiry (user_id, plan_type, subscript_type, expiry_date, is_active)
                        VALUES (%s, 'free', 'MONTHLY', date_trunc('month', CURRENT_TIMESTAMP) + interval '1 month' - interval '1 second', TRUE)
                    """, (uid,))
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"✗ Failed to create payment/billing tables: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def create_isp_tables(self) -> bool:
        """Create empty nodemaven_isps and evomi_isps tables"""
        queries = [
            """
            CREATE TABLE IF NOT EXISTS nodemaven_isps (
                country_code VARCHAR(10) PRIMARY KEY,
                isp_code VARCHAR(100) NOT NULL,
                updated_at TIMESTAMP NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS evomi_isps (
                country_code VARCHAR(10) PRIMARY KEY,
                isp_code VARCHAR(100) NOT NULL,
                updated_at TIMESTAMP NOT NULL
            );
            """
        ]
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            for q in queries:
                cursor.execute(q)
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"✗ Failed to create ISP tables: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def populate_isps_if_keys_exist(self):
        """Populate nodemaven_isps and evomi_isps if API keys are defined in environment config"""
        evomi_key = os.getenv("EVOMI_PREMIUM_ISP_APIKEY")
        nodemaven_key = os.getenv("NODEMAVEN_ISP_APIKEY")

        if not evomi_key and not nodemaven_key:
            logger.info("ℹ Skipping ISP tables population (EVOMI_PREMIUM_ISP_APIKEY / NODEMAVEN_ISP_APIKEY not found in .env)")
            return

        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()

            countries = set()
            if evomi_key:
                logger.info("Fetching supported countries from Evomi API...")
                headers = {"x-apikey": evomi_key}
                try:
                    resp = requests.get("https://api.evomi.com/public/settings", headers=headers, timeout=15.0)
                    if resp.status_code == 200:
                        settings_data = resp.json()
                        isp_dict = settings_data.get("data", {}).get("rp", {}).get("isp", {})
                        
                        for k, v in isp_dict.items():
                            for c in v.get("countries", []):
                                countries.add(c.upper())
                        
                        logger.info(f"✓ Found {len(countries)} Evomi supported countries.")
                        
                        # Populate Evomi Database
                        for c in countries:
                            filtered_isps = {
                                k: v for k, v in isp_dict.items()
                                if c in [country.upper() for country in v.get("countries", [])]
                            }
                            if not filtered_isps:
                                continue
                            selected = None
                            for prio in PRIORITY_ISPS:
                                for key, val in filtered_isps.items():
                                    if prio in key.lower() or prio in val.get("label", "").lower():
                                        selected = key
                                        break
                                if selected:
                                    break
                            if not selected:
                                selected = list(filtered_isps.keys())[0]
                                
                            cur.execute("""
                            INSERT INTO evomi_isps (country_code, isp_code, updated_at)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (country_code) DO UPDATE
                            SET isp_code = EXCLUDED.isp_code, updated_at = EXCLUDED.updated_at
                            """, (c, selected, datetime.datetime.now()))
                        conn.commit()
                        logger.info("✓ Evomi ISP settings successfully populated in database.")
                except Exception as e:
                    logger.warning(f"Failed to populate Evomi ISPs: {e}")

            if nodemaven_key:
                if not countries:
                    # Default list of common country codes if Evomi fetch failed or skipped
                    countries = {"JP", "US", "IN", "DE", "FR", "GB", "CA", "AU", "SG", "NL"}
                
                logger.info("Fetching and storing Nodemaven ISPs in parallel...")
                
                def _fetch_nodemaven(country):
                    """Fetch and return nodemaven."""
                    headers = {"Authorization": f"x-api-key {nodemaven_key}", "Content-Type": "application/json"}
                    url = "https://api.nodemaven.com/api/v2/base/locations/isps/"
                    params = {"country__code": country.lower(), "limit": 100, "offset": 0}
                    try:
                        resp = requests.get(url, params=params, headers=headers, timeout=12.0)
                        if resp.status_code == 200:
                            data = resp.json()
                            all_isps = data.get("isps", [])
                            if not all_isps:
                                return country, None
                            
                            high = [isp for isp in all_isps if isp.get("effective_availability") == "high"]
                            medium = [isp for isp in all_isps if isp.get("effective_availability") == "medium"]
                            low = [isp for isp in all_isps if isp.get("effective_availability") == "low"]
                            
                            selected = None
                            # 1. Check priority ISPs in high availability
                            for p in PRIORITY_ISPS:
                                for isp in high:
                                    if p in isp.get("code", "").lower() or p in isp.get("name", "").lower():
                                        selected = isp.get("code")
                                        break
                                if selected: break
                            # 2. Fallback to first high
                            if not selected and high:
                                selected = high[0].get("code")
                            # 3. Check medium
                            if not selected:
                                for p in PRIORITY_ISPS:
                                    for isp in medium:
                                        if p in isp.get("code", "").lower() or p in isp.get("name", "").lower():
                                            selected = isp.get("code")
                                            break
                                    if selected: break
                            # 4. Fallback to medium
                            if not selected and medium:
                                selected = medium[0].get("code")
                            # 5. Low
                            if not selected:
                                for p in PRIORITY_ISPS:
                                    for isp in low:
                                        if p in isp.get("code", "").lower() or p in isp.get("name", "").lower():
                                            selected = isp.get("code")
                                            break
                                    if selected: break
                            # 6. Fallback to low
                            if not selected and low:
                                selected = low[0].get("code")
                                
                            return country, selected
                    except Exception as e:
                        logger.debug(f"Nodemaven fetch failed for {country}: {e}")
                    return country, None

                success_count = 0
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {executor.submit(_fetch_nodemaven, c): c for c in countries}
                    for future in as_completed(futures):
                        c, isp = future.result()
                        if isp:
                            cur.execute("""
                            INSERT INTO nodemaven_isps (country_code, isp_code, updated_at)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (country_code) DO UPDATE
                            SET isp_code = EXCLUDED.isp_code, updated_at = EXCLUDED.updated_at
                            """, (c, isp, datetime.datetime.now()))
                            success_count += 1
                conn.commit()
                logger.info(f"✓ Nodemaven ISPs populated successfully. Total records stored: {success_count}")

            cur.close()
        except Exception as e:
            logger.error(f"Error executing ISP tables population: {e}")
        finally:
            if conn:
                conn.close()

    def create_proxy_bandwidth_usage_table(self) -> bool:
        """Create proxy_bandwidth_usage table"""
        query = """
        CREATE TABLE IF NOT EXISTS proxy_bandwidth_usage (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(user_id) ON DELETE CASCADE,
            endpoint VARCHAR(50) NOT NULL,
            url_or_query TEXT NOT NULL,
            nodemaven BIGINT DEFAULT NULL,
            evomi_premium BIGINT DEFAULT NULL,
            evomi_core BIGINT DEFAULT NULL,
            final_status VARCHAR(20) DEFAULT 'success',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_proxy_bandwidth_usage_user_id ON proxy_bandwidth_usage(user_id);
        CREATE INDEX IF NOT EXISTS idx_proxy_bandwidth_usage_created_at ON proxy_bandwidth_usage(created_at);
        """
        return self.execute_query(query)

    def setup_all_tables(self) -> bool:
        """Execute table creation and population in topological order of dependencies"""
        logger.info("Starting GcrawlAI database setup...")

        # 1. Base identity tables
        if not self.create_users_table(): return False
        if not self.create_signup_otps_table(): return False
        if not self.create_api_keys_table(): return False

        # 2. Crawler & search tables
        if not self.create_crawl_jobs_table(): return False

        if not self.create_crawl_errors_table(): return False
        if not self.create_search_jobs_table(): return False
        if not self.create_search_errors_table(): return False

        # 3. Partitioned results & activity logs
        if not self.create_job_results_table(): return False
        if not self.create_activity_logs_table(): return False
        if not self.create_reported_issues_table(): return False
        if not self.create_admin_error_logs_table(): return False
        if not self.create_admin_emails_table(): return False
        if not self.create_proxy_bandwidth_usage_table(): return False

        # 4. System config & payment tables
        if not self.create_api_endpoints_table(): return False
        if not self.create_subscription_plans_tables(): return False
        if not self.create_payment_tables(): return False
        if not self.create_isp_tables(): return False
        if not self.create_custom_requests_table(): return False

        # 5. Dynamic population of ISP config tables (conditional)
        self.populate_isps_if_keys_exist()

        logger.info("✓ GcrawlAI Database setup completed successfully")
        return True

    def verify_tables_exist(self) -> bool:
        """Verify existence of all 20 target system database tables"""
        required_tables = [
            'users', 'signup_otps', 'crawl_jobs', 'reported_issues', 
            'api_keys', 'crawl_errors', 'activity_logs', 
            'job_results', 'search_jobs', 'search_errors', 'api_endpoints', 
            'monthly_subscription_plans', 'yearly_subscription_plans', 'user_plans', 
            'payment_requests', 'plan_expiry', 'subscriptions', 'nodemaven_isps', 'evomi_isps',
            'admin_error_logs', 'custom_requests', 'admin_emails'
        ]
        
        verify_query = """
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public';
        """
        
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute(verify_query)
            tables = cursor.fetchall()
            cursor.close()
            
            table_names = [table[0].lower() for table in tables]
            all_exist = all(table in table_names for table in required_tables)
            
            if all_exist:
                logger.info(f"✓ Verify succeeded: All {len(required_tables)} system tables are successfully registered in database schema.")
            else:
                missing = [t for t in required_tables if t not in table_names]
                logger.warning(f"✗ Database Verification warning: Missing tables: {', '.join(missing)}")
            
            return all_exist
        except Exception as e:
            logger.error(f"✗ Failed to verify database tables schema: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()

    def drop_all_tables(self) -> bool:
        """Drop all GcrawlAI tables (USE WITH EXTREME CAUTION)"""
        tables = [
            'signup_otps', 'users', 'crawl_jobs', 'reported_issues', 
            'api_keys', 'crawl_errors', 'activity_logs', 'job_results', 'search_jobs', 
            'search_errors', 'api_endpoints', 'monthly_subscription_plans', 'yearly_subscription_plans', 'user_plans', 
            'payment_requests', 'plan_expiry', 'subscriptions', 'nodemaven_isps', 'evomi_isps',
            'admin_error_logs', 'custom_requests', 'admin_emails'
        ]
        
        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            for table in tables:
                cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
            conn.commit()
            cursor.close()
            logger.warning("⚠ All GcrawlAI system tables have been dropped.")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to drop tables: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()


def main():
    """Main execution function"""
    try:
        BASE_DIR = Path(__file__).resolve().parent.parent.parent
        config_path = BASE_DIR / "config.yaml"

        db_setup = DatabaseSetup(str(config_path))
        success = db_setup.setup_all_tables()
        
        if success:
            db_setup.verify_tables_exist()
            logger.info("=" * 60)
            logger.info("GcrawlAI Database Setup Completed Successfully!")
            logger.info("=" * 60)
        else:
            logger.error("=" * 60)
            logger.error("GcrawlAI Database Setup Failed!")
            logger.error("=" * 60)
            return False
        return True
    except Exception as e:
        logger.error(f"Database setup error: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)