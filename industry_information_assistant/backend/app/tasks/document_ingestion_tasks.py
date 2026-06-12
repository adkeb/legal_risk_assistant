"""Celery tasks for document ingestion."""
from __future__ import annotations

from core.celery_app import celery_app
from core.database import SessionLocal
from service.ingestion_pipeline_v2 import run_ingestion_pipeline


@celery_app.task(bind=True, name="document_ingestion.run", max_retries=3, default_retry_delay=30)
def run_document_ingestion(self, document_id: str, job_id: str) -> dict:
    db = SessionLocal()
    try:
        return run_ingestion_pipeline(db, document_id=document_id, job_id=job_id)
    except Exception as exc:
        retries = getattr(getattr(self, "request", None), "retries", 0)
        if retries < 3 and hasattr(self, "retry"):
            raise self.retry(exc=exc, countdown=min(30 * (retries + 1), 120))
        raise
    finally:
        db.close()
