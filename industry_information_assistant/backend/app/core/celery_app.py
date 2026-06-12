"""Celery application for durable ingestion jobs."""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Callable


def _redis_url(db: int) -> str:
    host = os.getenv("REDIS_HOST", "redis")
    port = os.getenv("REDIS_PORT", "6379")
    password = os.getenv("REDIS_PASSWORD", "")
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"


try:
    from celery import Celery

    celery_app = Celery(
        "industry_information_assistant",
        broker=os.getenv("CELERY_BROKER_URL", _redis_url(1)),
        backend=os.getenv("CELERY_RESULT_BACKEND", _redis_url(2)),
        include=["tasks.document_ingestion_tasks"],
    )
    celery_app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_default_queue="document_ingestion",
        timezone=os.getenv("TZ", "Asia/Shanghai"),
    )
except Exception:
    class _InlineTask:
        def __init__(self, fn: Callable[..., Any], bind: bool = False):
            self.fn = fn
            self.bind = bind
            self.__name__ = getattr(fn, "__name__", "inline_task")

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            if self.bind:
                return self.fn(_InlineTaskContext(), *args, **kwargs)
            return self.fn(*args, **kwargs)

        def delay(self, *args: Any, **kwargs: Any) -> Any:
            return self(*args, **kwargs)

        def apply_async(self, args: tuple | None = None, kwargs: dict | None = None, **_: Any) -> Any:
            return self(*(args or ()), **(kwargs or {}))

    class _InlineTaskContext:
        request = SimpleNamespace(retries=0)

        def retry(self, exc: Exception, **_: Any) -> None:
            raise exc

    class _InlineCelery:
        def task(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], _InlineTask]:
            bind = bool(kwargs.get("bind"))

            def decorator(fn: Callable[..., Any]) -> _InlineTask:
                return _InlineTask(fn, bind=bind)

            if args and callable(args[0]):
                return decorator(args[0])
            return decorator

    celery_app = _InlineCelery()
