import sys
from pathlib import Path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

import os
import psycopg2
import logging
from datetime import datetime
from dotenv import load_dotenv
from api.core.database import get_ist_now

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load .env
BASE_DIR = Path(__file__).resolve().parent.parent
dotenv_path = BASE_DIR / '.env'
load_dotenv(dotenv_path, override=True)


def reset_billing_and_free_plans():
    """
    Cron Job Script: Designed to run DAILY.

    Steps:
      1. Delete expired rollover_credits rows (expiry_date < now).
      2. Downgrade users whose paid plan_expiry has passed → free plan, reset used_requests.
      3. On the 1st of the month only: reset used_requests to 0 and extend expiry for all free plans.
    """
    logger.info("=" * 60)
    logger.info("Starting Daily Billing & Free Plan Reset Cron Job...")
    logger.info(f"Run time: {get_ist_now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    conn = None
    try:
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            database=os.getenv("POSTGRES_DATABASE", "Dev_tamil"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "password")
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute("SET TIME ZONE 'Asia/Kolkata';")
            conn.commit()
        except Exception as e:
            logger.warning(f"Failed to set session timezone to Asia/Kolkata: {e}")
        conn.autocommit = False
        cursor = conn.cursor()

        # ─────────────────────────────────────────────────────────────
        # STEP 1: Cleanup expired rollover_credits rows
        # Any row whose expiry_date has passed is stale and should be removed.
        # ─────────────────────────────────────────────────────────────
        logger.info("Step 1: Cleaning up expired rollover_credits...")
        cursor.execute("""
            DELETE FROM rollover_credits
            WHERE expiry_date < CURRENT_TIMESTAMP
            RETURNING id, user_id, credits
        """)
        deleted_rows = cursor.fetchall()
        if deleted_rows:
            logger.info(f"  Deleted {len(deleted_rows)} expired rollover credit pool(s):")
            for row in deleted_rows:
                logger.info(f"    → Rollover ID {row[0]}: user_id={row[1]}, credits={row[2]} (expired)")
        else:
            logger.info("  No expired rollover credit pools found.")

        # ─────────────────────────────────────────────────────────────
        # STEP 2: Downgrade expired Paid Plans → Free
        # ─────────────────────────────────────────────────────────────
        logger.info("Step 2: Checking for expired paid plans to downgrade...")
        cursor.execute("""
            SELECT user_id, plan_type FROM plan_expiry
            WHERE expiry_date < CURRENT_TIMESTAMP
            AND plan_type != 'free'
        """)
        expired_users = cursor.fetchall()

        if expired_users:
            logger.info(f"  Found {len(expired_users)} user(s) with expired paid plans.")
        else:
            logger.info("  No expired paid plans found.")

        for user in expired_users:
            uid = user[0]
            old_plan = user[1]
            logger.info(f"  Downgrading user {uid} from '{old_plan}' → 'free'...")

            # Reset user_plans to free
            cursor.execute("""
                UPDATE user_plans
                SET plan_type = 'free',
                    used_requests = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
            """, (uid,))

            # Update plan_expiry record to free
            cursor.execute("""
                UPDATE plan_expiry
                SET plan_type = 'free',
                    subscript_type = 'MONTHLY',
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
            """, (uid,))

        # ─────────────────────────────────────────────────────────────
        # STEP 3: Monthly reset for Free Plans (runs only on 1st of month)
        # ─────────────────────────────────────────────────────────────
        today = get_ist_now()
        if today.day == 1:
            logger.info("Step 3: Today is the 1st of the month. Resetting all 'free' plans...")

            # Reset used_requests to 0 for all free users
            cursor.execute("""
                UPDATE user_plans
                SET used_requests = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE plan_type = 'free'
            """)

            # Extend expiry to the end of the current calendar month
            cursor.execute("""
                UPDATE plan_expiry
                SET expiry_date = date_trunc('month', CURRENT_TIMESTAMP) + interval '1 month' - interval '1 second',
                    is_active = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE plan_type = 'free'
            """)
            logger.info("  Free plan limits reset and expiry extended to end of current month.")
        else:
            logger.info(f"Step 3: Skipped (not 1st of month — today is {today.strftime('%Y-%m-%d')}).")

        conn.commit()
        logger.info("=" * 60)
        logger.info("✅ Daily billing reset completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error during billing reset: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    reset_billing_and_free_plans()
