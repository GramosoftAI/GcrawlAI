import base64
import json
import time
import uuid
from typing import Any, Dict, Optional


ARTIFACT_REF_PREFIX = "artifact://"


def make_artifact_ref(artifact_id: str) -> str:
    return f"{ARTIFACT_REF_PREFIX}{artifact_id}"


def parse_artifact_ref(ref: Optional[str]) -> Optional[str]:
    if not ref or not isinstance(ref, str):
        return None
    if not ref.startswith(ARTIFACT_REF_PREFIX):
        return None
    artifact_id = ref[len(ARTIFACT_REF_PREFIX):].strip()
    return artifact_id or None


def ensure_crawl_job(
    conn,
    *,
    crawl_id: str,
    url: str,
    crawl_mode: str,
    enable_seo: bool = False,
    enable_html: bool = False,
    enable_ss: bool = False,
    enable_md: bool = False,
    task_id: Optional[str] = None,
    user_id: Optional[int] = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO crawl_jobs
            (crawl_id, url, crawl_mode, created_at, updated_at, task_id, SEO, HTML, Screenshot, Markdown, user_id)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP, NULL, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (crawl_id) DO NOTHING
        """,
        (
            crawl_id,
            url,
            crawl_mode,
            task_id,
            enable_seo,
            enable_html,
            enable_ss,
            enable_md,
            user_id,
        ),
    )
    cur.close()


def _serialize_content(content: Any, content_kind: str) -> str:
    if content_kind == "json":
        return json.dumps(content, ensure_ascii=False, indent=2)
    if content_kind == "binary":
        if isinstance(content, bytes):
            return base64.b64encode(content).decode("utf-8")
        if isinstance(content, str):
            return content
        raise TypeError("Binary artifact content must be bytes or base64 string.")
    if content is None:
        return ""
    return str(content)


def _wait_for_crawl_job(conn, crawl_id: str, retries: int = 15, delay_s: float = 0.2):
    for attempt in range(retries):
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM crawl_jobs WHERE crawl_id = %s",
            (crawl_id,),
        )
        exists = cur.fetchone() is not None
        cur.close()
        if exists:
            return
        conn.rollback()
        if attempt < retries - 1:
            time.sleep(delay_s)

    raise RuntimeError(
        f"crawl_jobs row was not visible for crawl_id={crawl_id} after waiting."
    )


def upsert_crawl_artifact(
    conn,
    *,
    crawl_id: str,
    artifact_type: str,
    content: Any,
    content_kind: str = "text",
    page_url: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    artifact_id = str(uuid.uuid4())
    payload = _serialize_content(content, content_kind)
    normalized_page_url = page_url or ""

    _wait_for_crawl_job(conn, crawl_id)

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO crawl_artifacts
            (artifact_id, crawl_id, page_url, artifact_type, content_kind, title, content)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (crawl_id, page_url, artifact_type) DO UPDATE SET
            title = EXCLUDED.title,
            content_kind = EXCLUDED.content_kind,
            content = EXCLUDED.content,
            updated_at = CURRENT_TIMESTAMP
        RETURNING artifact_id
        """,
        (
            artifact_id,
            crawl_id,
            normalized_page_url,
            artifact_type,
            content_kind,
            title,
            payload,
        ),
    )
    row = cur.fetchone()
    cur.close()
    stored_id = row[0] if row else artifact_id
    return make_artifact_ref(stored_id)


def get_crawl_artifact(conn, artifact_ref: str) -> Optional[Dict[str, Any]]:
    artifact_id = parse_artifact_ref(artifact_ref)
    if not artifact_id:
        return None

    cur = conn.cursor()
    cur.execute(
        """
        SELECT artifact_id, crawl_id, page_url, artifact_type, content_kind, title, content
        FROM crawl_artifacts
        WHERE artifact_id = %s
        """,
        (artifact_id,),
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        return None

    return {
        "artifact_id": row[0],
        "crawl_id": row[1],
        "page_url": row[2],
        "artifact_type": row[3],
        "content_kind": row[4],
        "title": row[5],
        "content": row[6],
    }
