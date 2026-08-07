import logging
import psycopg2
from psycopg2 import pool as psycopg2_pool
from contextlib import contextmanager
from typing import Union
from datetime import datetime, timezone, timedelta

# India Standard Time (IST) offset is UTC +5:30
ist_tz = timezone(timedelta(hours=5, minutes=30))

def get_ist_now() -> datetime:
    """Returns the current timezone-aware datetime in Asia/Kolkata timezone (IST)"""
    return datetime.now(ist_tz)


from api.core.config_setup import get_db_config

logger = logging.getLogger(__name__)

_db_pool = None

def _init_db_pool():
    """Initialize the database connection pool (call once at startup)"""
    global _db_pool
    db_config = get_db_config()
    # ThreadedConnectionPool is thread-safe (FastAPI serves sync endpoints in a thread pool)
    _db_pool = psycopg2_pool.ThreadedConnectionPool(
        minconn=5,
        maxconn=50,
        **db_config
    )
    logger.info(f"✓ DB connection pool created (ThreadedConnectionPool, min=5, max=50)")

@contextmanager
def get_pooled_connection(max_retries: int = 3):
    """
    Context manager that borrows a connection from the pool and returns it when done.
    Automatically detects and discards stale/broken connections (e.g. SSL closed
    unexpectedly, server gone away) and retries with a fresh connection.
    """
    global _db_pool
    if not _db_pool:
        raise RuntimeError("Database pool is not initialized. Call _init_db_pool() first.")
        
    conn = None
    last_error = None
    
    # 1. Obtain and validate a connection from the pool
    for attempt in range(1, max_retries + 1):
        try:
            conn = _db_pool.getconn()
            
            # Set connection timezone to Asia/Kolkata (IST).
            # This also serves as a lightweight health check to verify the connection is active.
            with conn.cursor() as test_cursor:
                test_cursor.execute("SET TIME ZONE 'Asia/Kolkata';")
            
            # Connection is valid, exit the retry loop
            break
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last_error = e
            if conn is not None:
                try:
                    _db_pool.putconn(conn, close=True)  # removes and closes the stale connection
                except Exception:
                    pass
                conn = None
            logger.warning(
                f"Stale DB connection on attempt {attempt}/{max_retries}: {e}. "
                + ("Retrying with fresh connection..." if attempt < max_retries else "No more retries.")
            )
            
    if conn is None:
        if last_error:
            raise last_error
        else:
            raise psycopg2.OperationalError("Could not retrieve a valid connection from the pool")

    # 2. Yield the connection and handle exceptions raised in the client block
    try:
        yield conn
    except Exception as e:
        # Check if the exception raised during client execution was a connection drop
        is_conn_error = isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError))
        if conn is not None:
            try:
                if is_conn_error:
                    _db_pool.putconn(conn, close=True)  # discard broken connection
                else:
                    conn.rollback()
                    _db_pool.putconn(conn)
            except Exception:
                pass
            conn = None
        raise  # Re-raise the exception to respect the context manager generator protocol
    finally:
        # 3. If no exception occurred, return the connection to the pool normally
        if conn is not None:
            try:
                _db_pool.putconn(conn)
            except Exception:
                pass

class PooledConnectionWrapper:
    def __init__(self, pool, conn):
        """Init."""
        self._pool = pool
        self._conn = conn

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._conn.__exit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        """Close."""
        try:
            if self._conn and self._pool:
                self._pool.putconn(self._conn)
        except Exception as e:
            logger.warning(f"Error returning connection to pool: {e}")
        finally:
            self._conn = None
            self._pool = None

# Wrapper for backwards compatibility using the pool
def get_db_connection():
    """Get a connection from the pool. Caller MUST return it via pool.putconn() or conn.close()."""
    global _db_pool
    if _db_pool is None:
        _init_db_pool()
    conn = _db_pool.getconn()
    return PooledConnectionWrapper(_db_pool, conn)

def log_activity(user_id: Union[int, str], endpoint: str, url: str, status: str, job_id: str = None, time_taken: str = None) -> None:
    """Log an activity to the activity_logs table"""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO activity_logs (user_id, endpoint, url, status, job_id, time_taken) VALUES (%s, %s, %s, %s, %s, %s)",
                    (user_id, endpoint, url, status, job_id, time_taken)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to log activity for user {user_id}: {e}")

def log_proxy_bandwidth(user_id: Union[int, str], endpoint: str, url_or_query: str, bandwidth_data: dict, status: str = 'success', job_id: str = None) -> None:
    """Log proxy bandwidth usage to proxy_bandwidth_usage table"""
    if not bandwidth_data or user_id == "demo":
        return
        
    try:
        def to_bytes(val):
            if val is None:
                return None
            if isinstance(val, float):
                return int(val * 1024 * 1024)
            return int(val)

        nodemaven = to_bytes(bandwidth_data.get('nodemaven'))
        thordata = to_bytes(bandwidth_data.get('thordata') or bandwidth_data.get('evomi_premium'))
        evomi_premium = to_bytes(bandwidth_data.get('evomi_premium'))
        evomi_core = to_bytes(bandwidth_data.get('evomi_core'))
        
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO proxy_bandwidth_usage 
                    (user_id, endpoint, url_or_query, nodemaven, thordata, evomi_premium, evomi_core, final_status, job_id) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, endpoint, url_or_query, nodemaven, thordata, evomi_premium, evomi_core, status, job_id)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to log proxy bandwidth for user {user_id}: {e}")

def get_activity_logs(user_id: Union[int, str], days: int = 7, endpoint: str = None) -> list:
    """Fetch activity logs for a specific user"""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT a.job_id, a.endpoint, a.url, a.status, a.time_taken, a.created_at, j.json_content 
                    FROM activity_logs a
                    LEFT JOIN job_results j ON a.job_id = j.job_id
                    WHERE a.user_id = %s AND a.created_at >= CURRENT_DATE - INTERVAL '%s days'
                """
                params = [str(user_id), days]
                
                if endpoint:
                    query += " AND a.endpoint = %s"
                    params.append(endpoint)
                    
                query += """
                    ORDER BY a.created_at DESC
                    LIMIT 1000
                """
                
                cursor.execute(query, tuple(params))
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to fetch activity logs for user {user_id}: {e}")
        return []

def update_activity_log_time(job_id: str, time_taken: str) -> None:
    """Update the time_taken column for a specific job in the activity_logs table"""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE activity_logs SET time_taken = %s WHERE job_id = %s",
                    (time_taken, job_id)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to update activity log time for job {job_id}: {e}")

def update_activity_log_status(job_id: str, status: str) -> None:
    """Update the status column for a specific job in the activity_logs table"""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE activity_logs SET status = %s WHERE job_id = %s",
                    (status.upper(), job_id)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to update activity log status for job {job_id}: {e}")

import json

def upsert_job_result(job_id: str, payload: dict, user_id: str = None) -> None:
    """Upserts a JSON payload into the job_results table, appending to the JSONB array."""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                # We use an ON CONFLICT alternative or direct UPDATE then INSERT 
                # because we partitioned by created_at and might not know created_at exactly for upsert.
                # However, UPDATE job_results SET json_content = json_content || new_array WHERE job_id = %s is best.
                
                payload_str = json.dumps([payload])
                
                cursor.execute(
                    "UPDATE job_results SET json_content = json_content || %s::jsonb WHERE job_id = %s",
                    (payload_str, job_id)
                )
                
                if cursor.rowcount == 0:
                    cursor.execute(
                        "INSERT INTO job_results (job_id, user_id, json_content) VALUES (%s, %s, %s::jsonb)",
                        (job_id, user_id, payload_str)
                    )
            conn.commit()
            logger.info(f"✅ Successfully saved/updated job result in Postgres DB for job_id: {job_id}")
    except Exception as e:
        logger.error(f"Failed to upsert job result for job {job_id}: {e}")

def get_usage_summary(user_id: Union[int, str], start_dt, end_dt) -> list:
    """Fetch daily request counts segmented by endpoint for a user in a date range"""
    import datetime
    try:
        # Convert dates to timestamp limits
        start_ts = datetime.datetime.combine(start_dt, datetime.time.min)
        end_ts = datetime.datetime.combine(end_dt, datetime.time.max)
        
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT 
                        DATE(created_at) AS date_only,
                        COUNT(*) FILTER (WHERE UPPER(endpoint) = '/SCRAPE') AS scrape_count,
                        COUNT(*) FILTER (WHERE UPPER(endpoint) = '/CRAWL') AS crawl_count,
                        COUNT(*) FILTER (WHERE UPPER(endpoint) = '/SEARCH') AS search_count,
                        COUNT(*) FILTER (WHERE UPPER(endpoint) = '/SCREENSHOT') AS screenshot_count,
                        COUNT(*) FILTER (WHERE UPPER(endpoint) = '/LINKS') AS links_count,
                        COUNT(*) AS total_count
                    FROM activity_logs
                    WHERE user_id = %s AND created_at >= %s AND created_at <= %s
                    GROUP BY DATE(created_at)
                    ORDER BY date_only ASC
                """
                cursor.execute(query, (str(user_id), start_ts, end_ts))
                results = []
                for row in cursor.fetchall():
                    results.append({
                        "date": row[0].strftime("%Y-%m-%d") if isinstance(row[0], datetime.date) else str(row[0]),
                        "scrape_count": int(row[1] or 0),
                        "crawl_count": int(row[2] or 0),
                        "search_count": int(row[3] or 0),
                        "screenshot_count": int(row[4] or 0),
                        "links_count": int(row[5] or 0),
                        "total_count": int(row[6] or 0)
                    })
                return results
    except Exception as e:
        logger.error(f"Failed to fetch usage summary for user {user_id}: {e}")
        return []

def get_user_remaining_credits(user_id: Union[int, str]) -> int:
    """Fetch remaining credits (total_requests - used_requests) for a user"""
    try:
        # Try to convert to int since user_plans.user_id is integer
        try:
            db_user_id = int(user_id)
        except ValueError:
            return 0
            
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        CASE WHEN e.subscript_type = 'YEARLY' THEN COALESCE(ys.credits_included, ms.credits_included, 500) ELSE COALESCE(ms.credits_included, 500) END as total_requests, 
                        u.used_requests
                    FROM user_plans u
                    LEFT JOIN plan_expiry e ON u.user_id = e.user_id
                    LEFT JOIN monthly_subscription_plans ms ON u.plan_type = ms.plan_key
                    LEFT JOIN yearly_subscription_plans ys ON u.plan_type = ys.plan_key
                    WHERE u.user_id = %s
                """, (db_user_id,))
                row = cursor.fetchone()
                if row:
                    total, used = row[0], row[1]
                    remaining = total - used
                    return max(0, remaining)
                return 0
    except Exception as e:
        logger.error(f"Failed to fetch remaining credits for user {user_id}: {e}")
        return 0

def get_admin_recipient_emails() -> str:
    """
    Get admin recipient email addresses from the `admin_emails` table in the database.
    Does NOT fall back to environment variables or config.yaml settings.
    """
    emails = []
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cur:
                # We query from public.admin_emails table
                cur.execute("SELECT email FROM admin_emails ORDER BY id ASC")
                rows = cur.fetchall()
                emails = [r[0] for r in rows if r[0]]
    except Exception as e:
        logger.warning(f"Failed to fetch admin emails from database: {e}")

    return ",".join(emails)

def get_admin_recipient_emails() -> str:
    """
    Get admin recipient email addresses.
    First tries to retrieve from the `admin_emails` table in the database.
    If none are found, falls back to the ADMIN_EMAIL environment variable or config email setting.
    """
    import os
    from api.core.config_setup import load_config
    
    emails = []
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cur:
                # We query from public.admin_emails table
                cur.execute("SELECT email FROM admin_emails ORDER BY id ASC")
                rows = cur.fetchall()
                emails = [r[0] for r in rows if r[0]]
    except Exception as e:
        logger.warning(f"Failed to fetch admin emails from database (it might not exist yet): {e}")

    if emails:
        return ",".join(emails)

    try:
        config = load_config()
        smtp_config = config.get("email", {})
        fallback = os.getenv("ADMIN_EMAIL") or smtp_config.get("from_email", "")
        return fallback
    except Exception as e:
        logger.error(f"Failed to load fallback admin email: {e}")
        return os.getenv("ADMIN_EMAIL", "")
