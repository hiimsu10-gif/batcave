"""A small database-backed job queue.

Deliveries (big WAV albums over SFTP) can take minutes, too long for a web
request. The admin page queues a job; `suprm worker` picks it up. No Redis or
extra service needed: the jobs table lives in the same database.
"""
from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Job, JobStatus

log = logging.getLogger("suprm.jobs")

HANDLERS: dict[str, Callable[[Session, dict], None]] = {}


def handler(kind: str):
    def register(fn):
        HANDLERS[kind] = fn
        return fn
    return register


def enqueue(session: Session, kind: str, payload: dict) -> Job:
    job = Job(kind=kind, payload=payload)
    session.add(job)
    session.flush()
    return job


def _claim(session: Session) -> Job | None:
    now = datetime.now(timezone.utc)
    stmt = (select(Job).where(Job.status == JobStatus.queued, Job.run_after <= now)
            .order_by(Job.id).limit(1))
    if session.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)  # several workers can run safely
    job = session.scalar(stmt)
    if job:
        job.status = JobStatus.running
        job.attempts += 1
        session.commit()
    return job


def run_pending(session: Session, limit: int = 50) -> int:
    _load_handlers()
    done = 0
    while done < limit and (job := _claim(session)):
        try:
            HANDLERS[job.kind](session, job.payload)
            job.status = JobStatus.done
            job.finished_at = datetime.now(timezone.utc)
        except Exception as exc:  # noqa: BLE001 - a job must never kill the worker
            session.rollback()
            job = session.get(Job, job.id)
            job.last_error = f"{exc}\n{traceback.format_exc()[-2000:]}"
            if job.attempts >= job.max_attempts:
                job.status = JobStatus.failed
                job.finished_at = datetime.now(timezone.utc)
                _on_final_failure(session, job, exc)
            else:
                job.status = JobStatus.queued
                job.run_after = datetime.now(timezone.utc) + timedelta(minutes=2 ** job.attempts)
            log.exception("job %s (%s) failed", job.id, job.kind)
        session.commit()
        done += 1
    return done


def _on_final_failure(session: Session, job: Job, exc: Exception) -> None:
    if job.kind == "deliver":
        from .models import Delivery, DeliveryStatus

        delivery = session.get(Delivery, job.payload.get("delivery_id"))
        if delivery:
            delivery.status = DeliveryStatus.failed
            delivery.error = str(exc)


def work_forever(session_factory, poll_seconds: float = 5.0) -> None:
    log.info("worker started")
    while True:
        with session_factory() as session:
            ran = run_pending(session)
        if not ran:
            time.sleep(poll_seconds)


def _load_handlers() -> None:
    from .delivery import service  # noqa: F401  (registers "deliver")
