import sys
import os
import asyncio
import threading
import time

# Add root directory to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from api.auth_manager import AuthManager
from api.db_setup import DatabaseSetup

def run_db_setup():
    setup = DatabaseSetup(os.path.join(BASE_DIR, "config.yaml"))
    success = setup.setup_all_tables()
    print("DB Setup Success:", success)

def test_auth_manager_connections():
    auth = AuthManager("config.yaml")

    def worker(i):
        try:
            # We call get_user_by_id multiple times concurrently to see if pool is exhausted
            # Since get_user_by_id uses _db_connection_context it should return connections
            user = auth.get_user_by_id(1)
            print(f"Worker {i} success")
        except Exception as e:
            print(f"Worker {i} failed: {e}")

    threads = []
    # Maximum connections is config depends, we changed it to 50
    # Let's spawn 100 threads to verify pool queues or errors out
    for i in range(100):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()
        time.sleep(0.01)

    for t in threads:
        t.join()

if __name__ == "__main__":
    run_db_setup()
    test_auth_manager_connections()
