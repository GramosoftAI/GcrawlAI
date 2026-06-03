import logging
import psycopg2
from psycopg2 import pool as psycopg2_pool
from contextlib import contextmanager

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
        
    last_error = None
    for attempt in range(1, max_retries + 1):
        conn = None
        try:
            conn = _db_pool.getconn()

            # Probe the connection: poll() checks the socket without hitting the server.
            # If the connection is broken psycopg2 raises OperationalError immediately.
            conn.poll()

            yield conn
            return  # success — exit the retry loop

        except psycopg2.OperationalError as e:
            last_error = e
            # SSL closed / server restarted / network hiccup — discard this connection
            if conn is not None:
                try:
                    _db_pool.putconn(conn, close=True)  # removes it from the pool
                except Exception:
                    pass
                conn = None
            logger.warning(
                f"Stale DB connection on attempt {attempt}/{max_retries}: {e}. "
                + ("Retrying with fresh connection..." if attempt < max_retries else "No more retries.")
            )

        except Exception:
            # Non-connection error — rollback and return connection to pool normally
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
                try:
                    _db_pool.putconn(conn)
                except Exception:
                    pass
                conn = None
            raise

        finally:
            # Safety net: return connection if it was yielded successfully
            if conn is not None:
                try:
                    _db_pool.putconn(conn)
                except Exception:
                    pass

    raise last_error

# Legacy wrapper for backwards compatibility
def get_db_connection():
    """Get a connection from the pool. Caller MUST return it via pool.putconn()."""
    global _db_pool
    return _db_pool.getconn()

def log_activity(user_id: int, endpoint: str, url: str, status: str, job_id: str = None) -> None:
    """Log an activity to the activity_logs table"""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO activity_logs (user_id, endpoint, url, status, job_id) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, endpoint, url, status, job_id)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to log activity for user {user_id}: {e}")

def get_activity_logs(user_id: int, days: int = 7, endpoint: str = None) -> list:
    """Fetch activity logs for a specific user"""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                    SELECT a.job_id, a.endpoint, a.url, a.status, a.created_at, j.json_content 
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
                    LIMIT 100
                """
                
                cursor.execute(query, tuple(params))
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to fetch activity logs for user {user_id}: {e}")
        return []

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
