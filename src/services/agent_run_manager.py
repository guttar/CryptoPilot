"""Durable Agent run lifecycle with resumable events and real cancellation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict

import redis
from sqlalchemy import func

from src.database.models import AgentRun, AgentRunEvent
from src.database.sql_session import SessionLocal
from src.services.agent_service import AgentService
from src.settings import settings
from src.utils.logger import logger


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timed_out"}


class AgentRunManager:
    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}
        self._event_locks: Dict[str, asyncio.Lock] = {}
        self._redis = None

    def _redis_client(self):
        if self._redis is None:
            self._redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    def _cache_status(self, run_id: str, status: str) -> None:
        try:
            key = f"agent:run:{run_id}"
            client = self._redis_client()
            client.hset(key, mapping={"status": status, "updated_at": datetime.now(timezone.utc).isoformat()})
            client.expire(key, settings.AGENT_RUN_CACHE_TTL)
        except Exception as exc:
            logger.warning(f"Unable to cache Agent run status: {exc}")

    def _persist_event(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> int:
        with SessionLocal() as db:
            next_sequence = (
                db.query(func.coalesce(func.max(AgentRunEvent.sequence), 0))
                .filter(AgentRunEvent.run_id == run_id)
                .scalar()
                + 1
            )
            event = AgentRunEvent(
                run_id=run_id,
                sequence=next_sequence,
                event_type=event_type,
                payload=payload,
            )
            db.add(event)
            db.commit()
            return next_sequence

    async def emit(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> int:
        lock = self._event_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            return await asyncio.to_thread(self._persist_event, run_id, event_type, payload)

    def _set_status(
        self,
        run_id: str,
        status: str,
        *,
        answer: str | None = None,
        error: str | None = None,
        tool_trace: list | None = None,
    ) -> None:
        with SessionLocal() as db:
            run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
            if run is None:
                return
            run.status = status
            if status == "running" and run.started_at is None:
                run.started_at = datetime.now(timezone.utc)
            if status in TERMINAL_STATUSES:
                run.completed_at = datetime.now(timezone.utc)
            if answer is not None:
                run.answer = answer
            if error is not None:
                run.error = error
            if tool_trace is not None:
                run.tool_trace = tool_trace
            db.commit()
        self._cache_status(run_id, status)

    def start(self, run_id: str) -> None:
        existing = self._tasks.get(run_id)
        if existing and not existing.done():
            return
        cancel_event = asyncio.Event()
        self._cancel_events[run_id] = cancel_event
        task = asyncio.create_task(self._execute(run_id, cancel_event), name=f"agent-run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._cleanup(run_id))

    def _cleanup(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)
        self._cancel_events.pop(run_id, None)
        self._event_locks.pop(run_id, None)

    def _load_run(self, run_id: str) -> Dict[str, Any] | None:
        with SessionLocal() as db:
            run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
            if run is None:
                return None
            return {
                "question": run.question,
                "config": run.config_snapshot or {},
                "user_id": run.user_id,
            }

    async def _execute(self, run_id: str, cancel_event: asyncio.Event) -> None:
        record = await asyncio.to_thread(self._load_run, run_id)
        if record is None:
            return

        await asyncio.to_thread(self._set_status, run_id, "running")
        timeout_seconds = min(
            max(int((record["config"].get("execution_config") or {}).get("timeout", 60)), 1),
            settings.AGENT_MAX_TIMEOUT_SECONDS,
        )

        async def emit(event_type: str, payload: Dict[str, Any]) -> None:
            await self.emit(run_id, event_type, payload)

        try:
            async with asyncio.timeout(timeout_seconds):
                result = await AgentService().run(
                    record["question"],
                    record["config"],
                    session_id=f"agent:{run_id}",
                    user_id=record["user_id"],
                    emit=emit,
                    cancel_event=cancel_event,
                )
            await asyncio.to_thread(
                self._set_status,
                run_id,
                "completed",
                answer=result["answer"],
                tool_trace=result["tool_trace"],
            )
            await emit("run.completed", result)
        except asyncio.TimeoutError:
            message = f"Agent run exceeded the {timeout_seconds}s timeout"
            await asyncio.to_thread(self._set_status, run_id, "timed_out", error=message)
            await emit("run.timed_out", {"message": message})
        except asyncio.CancelledError:
            cancel_event.set()
            await asyncio.to_thread(self._set_status, run_id, "cancelled")
            await emit("run.cancelled", {"message": "Execution cancelled by user"})
        except Exception as exc:
            logger.exception(f"Agent run {run_id} failed")
            await asyncio.to_thread(self._set_status, run_id, "failed", error=str(exc))
            await emit("run.failed", {"message": str(exc)})

    async def cancel(self, run_id: str) -> bool:
        with SessionLocal() as db:
            run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
            if run is None or run.status in TERMINAL_STATUSES:
                return False
            run.cancel_requested = True
            db.commit()

        cancel_event = self._cancel_events.get(run_id)
        if cancel_event is not None:
            cancel_event.set()
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
        else:
            await asyncio.to_thread(self._set_status, run_id, "cancelled")
            await self.emit(run_id, "run.cancelled", {"message": "Execution cancelled by user"})
        return True


agent_run_manager = AgentRunManager()
