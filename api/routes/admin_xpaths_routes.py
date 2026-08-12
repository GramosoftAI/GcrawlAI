from fastapi import APIRouter, HTTPException, Depends
from typing import Dict
from api.core.database import get_pooled_connection
from pydantic import BaseModel

router = APIRouter(prefix="/admin/xpaths", tags=["Admin XPaths"])

class XPathUpdateRequest(BaseModel):
    xpaths: Dict[str, str]

@router.get("/{scraper_name}")
def get_xpaths(scraper_name: str):
    """
    Get the xpaths for a specific scraper as a key-value dictionary.
    """
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT field_name, xpath_value FROM scraper_xpaths WHERE scraper_name = %s",
                    (scraper_name,)
                )
                rows = cursor.fetchall()
                if not rows:
                    return {"status": "success", "data": {}}
                
                data = {row[0]: row[1] for row in rows}
                return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{scraper_name}")
def update_xpaths(scraper_name: str, request: XPathUpdateRequest):
    """
    Update or insert xpaths for a specific scraper.
    """
    if not request.xpaths:
        raise HTTPException(status_code=400, detail="No xpaths provided")

    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cursor:
                for field_name, xpath_value in request.xpaths.items():
                    cursor.execute(
                        """
                        INSERT INTO scraper_xpaths (scraper_name, field_name, xpath_value)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (scraper_name, field_name) 
                        DO UPDATE SET xpath_value = EXCLUDED.xpath_value, updated_at = CURRENT_TIMESTAMP
                        """,
                        (scraper_name, field_name, xpath_value)
                    )
            conn.commit()
        return {"status": "success", "message": f"XPaths for {scraper_name} updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
