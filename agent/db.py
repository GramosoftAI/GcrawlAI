import os
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import psycopg2
from psycopg2.extras import Json
import yaml


_CONFIG_CACHE: Optional[Dict[str, Any]] = None


def _substitute_env_vars(data):
    if isinstance(data, dict):
        return {key: _substitute_env_vars(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    if isinstance(data, str):
        def replace_var(match):
            var_name = match.group(1)
            default_value = match.group(2)
            return os.getenv(var_name, default_value or "")

        return re.sub(r"\$\{([^:}]+)(?::([^}]*))?\}", replace_var, data)
    return data


def _load_config() -> Dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        base_dir = Path(__file__).resolve().parent.parent
        config_path = base_dir / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
        _CONFIG_CACHE = _substitute_env_vars(raw_config)
    return _CONFIG_CACHE


def _db_config() -> Dict[str, Any]:
    config = _load_config()
    return config.get("postgres", {})


def get_db_connection():
    db = _db_config()
    return psycopg2.connect(
        host=db.get("host", "localhost"),
        port=db.get("port", 5432),
        database=db.get("database", "crawlerdb"),
        user=db.get("user", "postgres"),
        password=db.get("password", ""),
    )


@contextmanager
def db_conn():
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class AgentRepository:
    def create_job(self, job: Dict[str, Any]) -> None:
        with db_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO jobs
                    (job_id, prompt, urls, schema_json, strict_constrain, model,
                     max_credits, status, credits_used, result_json, error,
                     created_at, updated_at, expires_at)
                VALUES
                    (%s, %s, %s, %s, %s, %s,
                     %s, %s, %s, %s, %s,
                     %s, %s, %s)
                """,
                (
                    job["job_id"],
                    job["prompt"],
                    job.get("urls"),
                    Json(job.get("schema_json")) if job.get("schema_json") is not None else None,
                    job.get("strict_constrain", False),
                    job.get("model"),
                    job.get("max_credits"),
                    job.get("status", "processing"),
                    job.get("credits_used", 0),
                    Json(job.get("result_json")) if job.get("result_json") is not None else None,
                    job.get("error"),
                    job.get("created_at", datetime.utcnow()),
                    job.get("updated_at"),
                    job.get("expires_at"),
                ),
            )
            cur.close()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with db_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT job_id, prompt, urls, schema_json, strict_constrain, model,
                       max_credits, status, credits_used, result_json, error,
                       created_at, updated_at, expires_at
                FROM jobs WHERE job_id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            return None
        return {
            "job_id": row[0],
            "prompt": row[1],
            "urls": row[2],
            "schema_json": row[3],
            "strict_constrain": row[4],
            "model": row[5],
            "max_credits": row[6],
            "status": row[7],
            "credits_used": row[8] or 0,
            "result_json": row[9],
            "error": row[10],
            "created_at": row[11],
            "updated_at": row[12],
            "expires_at": row[13],
        }

    def update_job(self, job_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = datetime.utcnow()
        columns = []
        values = []
        for key, value in fields.items():
            if key in {"schema_json", "result_json"} and value is not None:
                value = Json(value)
            columns.append(f"{key} = %s")
            values.append(value)
        values.append(job_id)
        sql = f"UPDATE jobs SET {', '.join(columns)} WHERE job_id = %s"
        with db_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, tuple(values))
            cur.close()

    def increment_credits(self, job_id: str, amount: int) -> None:
        with db_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE jobs SET credits_used = COALESCE(credits_used, 0) + %s, updated_at = %s WHERE job_id = %s",
                (amount, datetime.utcnow(), job_id),
            )
            cur.close()

    def append_log(self, job_id: str, step: str, message: str) -> None:
        with db_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO job_logs (job_id, step, message, timestamp)
                VALUES (%s, %s, %s, %s)
                """,
                (job_id, step, message, datetime.utcnow()),
            )
            cur.close()

    def is_cancelled(self, job_id: str) -> bool:
        with db_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status FROM jobs WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
            cur.close()
        return bool(row and row[0] == "cancelled")
