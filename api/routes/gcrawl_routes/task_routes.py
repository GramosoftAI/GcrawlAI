import logging
from typing import Union, Optional
from fastapi import APIRouter, HTTPException, Header
from api.models.gcrawl_payloads import UserCrawlsResponse, UserCrawlJobResponse, CrawlPathsResponse
from api.core.database import get_pooled_connection

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/status/{job_id}")
def get_task_status(
    job_id: str,
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    recaptcha_token: Optional[str] = Header(None, alias="recaptcha-token")
):
    """Return task status."""
    from api.core.database import get_pooled_connection
    from api.core.security import validate_recaptcha_or_jwt
    from web_crawler.crawler.celery_config import celery_app

    # 1. Require at least one header
    if not x_api_key and not authorization and not recaptcha_token:
        raise HTTPException(
            status_code=400,
            detail="Must pass api key in header"
        )
        
    # 2. Validate using security engine
    try:
        user_id = validate_recaptcha_or_jwt(
            auth_header=authorization,
            recaptcha_header=recaptcha_token,
            api_key_header=x_api_key
        )
    except HTTPException as auth_err:
        if auth_err.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid API key or token")
        raise auth_err
        
    auth_user_id = str(user_id)

    # 3. Check ownership in activity_logs (or fallback to crawl_jobs)
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT user_id FROM activity_logs WHERE job_id = %s LIMIT 1",
                    (job_id,)
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        "SELECT user_id FROM crawl_jobs WHERE crawl_id = %s LIMIT 1",
                        (job_id,)
                    )
                    row = cursor.fetchone()
                    
                if not row:
                    raise HTTPException(status_code=404, detail="Job not found")
                    
                job_user_id = str(row[0])
                if job_user_id != auth_user_id:
                    raise HTTPException(status_code=404, detail="Job not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating ownership of job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check job ownership: {str(e)}")

    # 4. Check database to see if we already have a recorded outcome
    db_state = None
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cur:
                # Get the crawl job record
                cur.execute("SELECT updated_at FROM crawl_jobs WHERE crawl_id = %s LIMIT 1", (job_id,))
                row = cur.fetchone()
                if row:
                    updated_at = row[0]
                    if updated_at is None:
                        # Job is still in progress (pending or running)
                        db_state = "PENDING"
                    else:
                        # Job has finished. Check if we have results.
                        cur.execute("SELECT 1 FROM job_results WHERE job_id = %s LIMIT 1", (job_id,))
                        if cur.fetchone():
                            db_state = "SUCCESS"
                        else:
                            # If no results but updated_at is set, it might have failed
                            db_state = "FAILURE"
                else:
                    db_state = None
    except Exception as e:
        logger.error(f"Error querying job state from database for {job_id}: {e}")

    # 5. Check Celery task status
    task = celery_app.AsyncResult(job_id)
    celery_state = task.state

    # 6. Combine statuses
    # Celery defaults to PENDING if a task ID is unknown, so if database knows something, we trust it
    final_state = celery_state
    if celery_state == "PENDING" and db_state is not None:
        final_state = db_state

    return {
        "status_code": 200,
        "status": "success",
        "job_id": job_id,
        "task_id": job_id,  # For backwards compatibility with clients reading task_id
        "state": final_state,
        "result": task.result if task.ready() else None
    }

@router.get("/user/{user_id}", response_model=UserCrawlsResponse)
def get_user_crawls(user_id: Union[int, str]):
    """
    Returns all crawl jobs for a specific user_id.
    """
    try:
        from psycopg2.extras import RealDictCursor
        with get_pooled_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute(
                """
                SELECT 
                    user_id, crawl_id, url, crawl_mode, 
                    seo, html, 
                    screenshot, markdown, images,
                    links, 
                    created_at
                FROM crawl_jobs
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,)
            )
            rows = cur.fetchall()
            
            crawls = []
            for row in rows:
                crawls.append(UserCrawlJobResponse(**row))
                
            cur.close()
        
        return UserCrawlsResponse(
            status_code=200,
            status="success",
            crawls=crawls
        )
        
    except Exception as e:
        logger.error(f"Error fetching user crawls for {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch user crawls: {str(e)}")



@router.get("/data/{job_id}")
def get_crawl_data(
    job_id: str,
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    recaptcha_token: Optional[str] = Header(None, alias="recaptcha-token")
):
    """
    Returns the JSON payload directly from the job_results Postgres table.
    Requires authentication via X-API-Key, Authorization (JWT) header, or reCAPTCHA token.
    Checks if the job belongs to the authenticated user.
    """
    from api.core.database import get_pooled_connection
    from api.core.security import validate_recaptcha_or_jwt
    import json
    
    # 1. Require at least one header
    if not x_api_key and not authorization and not recaptcha_token:
        raise HTTPException(
            status_code=400,
            detail="Must pass api key in header"
        )
        
    # 2. Validate using security engine
    try:
        user_id = validate_recaptcha_or_jwt(
            auth_header=authorization,
            recaptcha_header=recaptcha_token,
            api_key_header=x_api_key
        )
    except HTTPException as auth_err:
        # Map validation errors to 401 for invalid api key/jwt/recaptcha
        if auth_err.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid API key or token")
        raise auth_err
        
    auth_user_id = str(user_id)
    
    # 3. Check ownership in activity_logs (or fallback to crawl_jobs)
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT user_id FROM activity_logs WHERE job_id = %s LIMIT 1",
                    (job_id,)
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        "SELECT user_id FROM crawl_jobs WHERE crawl_id = %s LIMIT 1",
                        (job_id,)
                    )
                    row = cursor.fetchone()
                    
                if not row:
                    raise HTTPException(status_code=404, detail="Job not found")
                    
                job_user_id = str(row[0])
                if job_user_id != auth_user_id:
                    raise HTTPException(status_code=404, detail="Job not found")
                    
                # 4. Fetch actual scraped JSON data
                cursor.execute("SELECT json_content FROM job_results WHERE job_id = %s", (job_id,))
                row = cursor.fetchone()
                if row:
                    data = row[0]
                    if isinstance(data, str):
                        data = json.loads(data)
                    return {
                        "status_code": 200,
                        "status": "success",
                        "job_id": job_id,
                        "data": data
                    }
                else:
                    raise HTTPException(status_code=404, detail="No data found for this job")
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching data for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch job data: {str(e)}")


@router.get("/results/{job_id}")
async def get_crawl_results(
    job_id: str,
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    recaptcha_token: Optional[str] = Header(None, alias="recaptcha-token")
):
    """
    Returns the final crawled data when the job has completed successfully (state: SUCCESS).
    Polls the status internally every 4 seconds if the job is still running/pending.
    """
    import asyncio

    # Max timeout: 10 minutes (600 seconds) to avoid hanging indefinitely
    timeout_seconds = 600
    elapsed = 0

    while elapsed < timeout_seconds:
        # 1. Reuse get_task_status to validate auth and fetch status
        status_response = get_task_status(
            job_id=job_id,
            x_api_key=x_api_key,
            authorization=authorization,
            recaptcha_token=recaptcha_token
        )
        
        state = status_response.get("state")
        
        if state == "SUCCESS":
            # 2. Reuse get_crawl_data to return the actual results
            return get_crawl_data(
                job_id=job_id,
                x_api_key=x_api_key,
                authorization=authorization,
                recaptcha_token=recaptcha_token
            )
        elif state == "FAILURE":
            raise HTTPException(
                status_code=400,
                detail="Crawl job failed. No results available."
            )
            
        # Wait 2 seconds before checking status again
        await asyncio.sleep(2)
        elapsed += 2

    raise HTTPException(
        status_code=504,
        detail="Gateway Timeout: Crawl job took too long to complete. Please check status endpoint."
    )
