import redis
import json
import os

import logging

logger = logging.getLogger(__name__)

redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,
    socket_timeout=2,
    socket_connect_timeout=2
)

def publish_event(crawl_id: str, payload: dict):
    try:
        redis_client.publish(f"crawl:{crawl_id}", json.dumps(payload))
    except Exception as e:
        logger.warning(f"Could not publish event to Redis (is Redis running?): {e}")
