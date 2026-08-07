import sys
from pathlib import Path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

import logging
import datetime
from api.core.database import get_pooled_connection

logger = logging.getLogger(__name__)

def init_gsearch_database() -> bool:
    """Creates the gsearch_results partitioned table and daily partition shards"""
    create_table_query = """
    CREATE TABLE IF NOT EXISTS gsearch_results (
        gsearch_id VARCHAR(64) NOT NULL,
        json_content JSONB DEFAULT '[]'::jsonb,
        status VARCHAR(20) DEFAULT 'processing' NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (gsearch_id, created_at)
    ) PARTITION BY RANGE (created_at);
    """
    
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                # 1. Create partitioned base table
                cursor.execute(create_table_query)
                
                # 2. Pre-create daily partitions for yesterday, today, and the next 10 days
                for i in range(-2, 11):
                    d = (datetime.datetime.now() + datetime.timedelta(days=i)).date()
                    d_next = d + datetime.timedelta(days=1)
                    part_name = f"gsearch_results_{d.strftime('%Y_%m_%d')}"
                    
                    cursor.execute(f"""
                        CREATE TABLE IF NOT EXISTS {part_name} PARTITION OF gsearch_results 
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
            logger.info("✓ gsearch_results table and daily partitions initialized/validated successfully.")
            return True
    except Exception as e:
        logger.error(f"✗ Failed to create partitioned gsearch_results table: {e}", exc_info=True)
        return False

def drop_old_gsearch_partitions(days_old: int = 2) -> int:
    """Drops gsearch_results daily partitions that are older than days_old days"""
    dropped_count = 0
    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days_old)
    
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                # Query all child partition tables belonging to parent 'gsearch_results'
                cursor.execute("""
                    SELECT child.relname
                    FROM pg_inherits
                    JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
                    JOIN pg_class child ON pg_inherits.inhrelid = child.oid
                    WHERE parent.relname = 'gsearch_results';
                """)
                partitions = cursor.fetchall()
                
                for (part_name,) in partitions:
                    try:
                        # Suffix format: YYYY_MM_DD
                        date_str = part_name.replace("gsearch_results_", "")
                        part_date = datetime.datetime.strptime(date_str, "%Y_%m_%d")
                        if part_date < cutoff_date:
                            cursor.execute(f"DROP TABLE IF EXISTS {part_name};")
                            dropped_count += 1
                            logger.info(f"Dropped old gsearch_results partition table: {part_name}")
                    except ValueError:
                        # In case partition name doesn't match the format
                        pass
            conn.commit()
    except Exception as e:
        logger.error(f"Error dropping old gsearch partitions: {e}")
        
    return dropped_count

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    from api.core.database import _init_db_pool
    logger.info("Initializing DB Pool for standalone setup...")
    _init_db_pool()
    
    logger.info("Setting up gsearch_results and daily partition shards...")
    init_gsearch_database()
