import logging
from fastapi import APIRouter, HTTPException
from api.models.payloads import UserCrawlsResponse, UserCrawlJobResponse, CrawlPathsResponse
from api.core.database import get_pooled_connection

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/status/{task_id}")
def get_task_status(task_id: str):
    from web_crawler.crawler.celery_config import celery_app

    task = celery_app.AsyncResult(task_id)

    return {
        "status_code": 200,
        "status": "success",
        "task_id": task_id,
        "state": task.state,
        "result": task.result if task.ready() else None
    }

@router.get("/user/{user_id}", response_model=UserCrawlsResponse)
def get_user_crawls(user_id: int):
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
def get_crawl_data(job_id: str):
    """
    Returns the JSON payload directly from the job_results Postgres table.
    """
    from api.core.database import get_pooled_connection
    import json
    
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
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
