import redis
import json
import os

redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True
)

def publish_event(crawl_id: str, payload: dict):
    redis_client.publish(f"crawl:{crawl_id}", json.dumps(payload))
