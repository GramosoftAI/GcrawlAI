import os
import psycopg2
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load .env
BASE_DIR = Path(__file__).resolve().parent.parent
dotenv_path = BASE_DIR / '.env'
load_dotenv(dotenv_path, override=True)

def reset_billing_and_free_plans():
    """
    Cron Job Script: Runs on the 1st of every month (or daily).
    1. Finds expired paid plans and downgrades them to free.
    2. Resets all 'free' plan limits (used_requests=0) and extends expiry to end of current month.
    """
    logger.info("Starting Billing & Free Plan Reset Cron Job...")
    
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            database=os.getenv("POSTGRES_DATABASE", "Dev_tamil"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "password")
        )
        conn.autocommit = False
        cursor = conn.cursor()
        
        # 1. Downgrade expired Paid Plans to Free Plan
        logger.info("Checking for expired paid plans...")
        cursor.execute("""
            SELECT user_id, plan_type FROM plan_expiry 
            WHERE expiry_date < CURRENT_TIMESTAMP 
            AND plan_type != 'free'
        """)
        expired_users = cursor.fetchall()
        
        for user in expired_users:
            uid = user[0]
            old_plan = user[1]
            logger.info(f"Downgrading user {uid} from {old_plan} to free plan...")
            
            # Update user_plans to free
            cursor.execute("""
                UPDATE user_plans 
                SET plan_type = 'free', 
                    used_requests = 0, 
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
            """, (uid,))
            
            # Update plan_expiry to free (expiry set in next step)
            cursor.execute("""
                UPDATE plan_expiry 
                SET plan_type = 'free', 
                    subscript_type = 'MONTHLY',
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
            """, (uid,))
        
        # 2. Reset ALL Free Plans (Reset used_requests to 0 and set expiry to End of Month)
        # ONLY run this part if today is the 1st of the month
        today = datetime.now()
        if today.day == 1:
            logger.info("Today is the 1st of the month. Resetting all 'free' plans for the new calendar month...")
            
            # Reset limits
            cursor.execute("""
                UPDATE user_plans 
                SET used_requests = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE plan_type = 'free'
            """)
            
            # Extend expiry to End of current month
            cursor.execute("""
                UPDATE plan_expiry 
                SET expiry_date = date_trunc('month', CURRENT_TIMESTAMP) + interval '1 month' - interval '1 second',
                    is_active = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE plan_type = 'free'
            """)
        else:
            logger.info(f"Today is {today.strftime('%Y-%m-%d')}. Skipping free plan monthly reset.")
            
        conn.commit()
        logger.info("✅ Billing & Free Plan Reset completed successfully!")
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error during billing reset: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    reset_billing_and_free_plans()
