import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def setup_db():
    try:
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            database=os.getenv("POSTGRES_DATABASE", "Dev_tamil"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "password")
        )
        conn.autocommit = True
        cursor = conn.cursor()

        print("Creating payment and plan tables...")

        # 1. user_plans
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_plans (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                plan_type VARCHAR(50) NOT NULL DEFAULT 'free',
                used_requests BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id)
            );
        """)

        # 2. payment_requests
        cursor.execute("""
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
        """)

        # 3. plan_expiry
        cursor.execute("""
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
        """)

        # 4. subscriptions (Stripe placeholder)
        cursor.execute("""
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
        """)

        # Drop obsolete columns from user_plans if they exist
        cursor.execute("ALTER TABLE user_plans DROP COLUMN IF EXISTS total_requests;")
        cursor.execute("ALTER TABLE user_plans DROP COLUMN IF EXISTS concurrency_limit;")

        print("Tables created successfully!")
        
        # Check existing users and assign free plan if they don't have one
        cursor.execute("SELECT user_id FROM users;")
        users = cursor.fetchall()
        for u in users:
            uid = u[0]
            cursor.execute("SELECT id FROM user_plans WHERE user_id = %s", (uid,))
            if not cursor.fetchone():
                print(f"Assigning free plan to existing user {uid}...")
                cursor.execute("""
                    INSERT INTO user_plans (user_id, plan_type, used_requests)
                    VALUES (%s, 'free', 0)
                """, (uid,))
                
                cursor.execute("""
                    INSERT INTO plan_expiry (user_id, plan_type, subscript_type, expiry_date, is_active)
                    VALUES (%s, 'free', 'MONTHLY', date_trunc('month', CURRENT_TIMESTAMP) + interval '1 month' - interval '1 second', TRUE)
                """, (uid,))

        print("Legacy users migrated successfully!")

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    setup_db()
