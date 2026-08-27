import os
import boto3
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables relative to project root
BASE_DIR = Path(__file__).resolve().parent.parent
dotenv_path = BASE_DIR / '.env'
load_dotenv(dotenv_path, override=True)

logger = logging.getLogger(__name__)

def cleanup_old_s3_data(days_threshold=7):
    region = os.getenv("AWS_REGION", "ap-south-1")
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    bucket = os.getenv("AWS_S3_BUCKET", "gramosoft")
    prefix = "gcrawl_outputs/"
    
    logger.info(f"[S3 CLEANUP] Connecting to S3 bucket '{bucket}' to clean up objects older than {days_threshold} days...")
    s3 = boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_threshold)
    logger.info(f"[S3 CLEANUP] Cutoff time (older than this will be deleted): {cutoff_time}")

    try:
        paginator = s3.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
        
        objects_to_delete = []
        scanned_count = 0
        deleted_count = 0
        
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    scanned_count += 1
                    key = obj['Key']
                    last_modified = obj['LastModified']  # Offset-aware UTC datetime
                    
                    if last_modified < cutoff_time:
                        objects_to_delete.append({'Key': key})
                        deleted_count += 1
                        
                        # Delete in batches of 1000 (S3 API limit)
                        if len(objects_to_delete) >= 1000:
                            logger.info(f"[S3 CLEANUP] Deleting batch of {len(objects_to_delete)} objects...")
                            s3.delete_objects(
                                Bucket=bucket,
                                Delete={'Objects': objects_to_delete}
                            )
                            objects_to_delete = []
                            
        # Delete any remaining objects
        if objects_to_delete:
            logger.info(f"[S3 CLEANUP] Deleting final batch of {len(objects_to_delete)} objects...")
            s3.delete_objects(
                Bucket=bucket,
                Delete={'Objects': objects_to_delete}
            )
            
        logger.info(f"[S3 CLEANUP] Scan complete under '{prefix}': Scanned={scanned_count}, Deleted={deleted_count}")
        return scanned_count, deleted_count
        
    except Exception as e:
        logger.error(f"[S3 CLEANUP] Error during programmatic S3 cleanup: {e}", exc_info=True)
        return 0, 0

async def run_daily_cleanup_loop():
    """FastAPI background task loop that runs every 24 hours to automatically clean up old S3 data."""
    logger.info("[S3 CLEANUP] S3 daily cleanup loop initialized. Waiting 5 minutes before first run...")
    await asyncio.sleep(300)  # Wait 5 minutes to avoid startup CPU spikes
    while True:
        try:
            logger.info("[S3 CLEANUP] Executing daily S3 cleanup task...")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, cleanup_old_s3_data, 7)
        except Exception as e:
            logger.error(f"[S3 CLEANUP] Error in background daily S3 cleanup task: {e}")
        
        logger.info("[S3 CLEANUP] Daily S3 cleanup task finished. Sleeping for 24 hours...")
        await asyncio.sleep(86400)  # Sleep for 24 hours (86400 seconds)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    cleanup_old_s3_data()
