"""In-process job runner for live guide generation.

Each job keeps its full event log, so a browser that connects late (or reconnects) replays
everything, then follows new events. Same-query jobs in flight are de-duplicated.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

MAX_CONCURRENT = 3


@dataclass
class Job:
    id: str
    query: str
    status: str = "queued"  # queued | running | done | error
    events: list[dict] = field(default_factory=list)
    slug: Optional[str] = None
    error: Optional[str] = None
    started: float = field(default_factory=time.time)
    _cond: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def push(self, ev: dict) -> None:
        ev = {**ev, "t": round(time.time() - self.started, 1)}
        async with self._cond:
            self.events.append(ev)
            self._cond.notify_all()

    async def follow(self):
        """Yield all events so far, then new ones until the job finishes."""
        i = 0
        while True:
            async with self._cond:
                while i >= len(self.events) and self.status not in ("done", "error"):
                    await self._cond.wait()
                batch = self.events[i:]
                finished = self.status in ("done", "error")
            for ev in batch:
                yield ev
            i += len(batch)
            if finished and i >= len(self.events):
                return


class JobManager:
    def __init__(self, runner):
        self.runner = runner  # async (query, on_event) -> Guide
        self.jobs: dict[str, Job] = {}
        self.by_query: dict[str, str] = {}
        self.sem = asyncio.Semaphore(MAX_CONCURRENT)

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def start(self, query: str) -> Job:
        key = query.strip().lower()
        if (jid := self.by_query.get(key)) and self.jobs[jid].status in ("queued", "running"):
            return self.jobs[jid]
        job = Job(id=uuid.uuid4().hex[:10], query=query.strip())
        self.jobs[job.id] = job
        self.by_query[key] = job.id
        asyncio.create_task(self._run(job))
        return job

    async def _run(self, job: Job) -> None:
        await job.push({"kind": "stage", "message": "Queued", "stage": "queued"})
        async with self.sem:
            job.status = "running"
            try:
                guide = await self.runner(job.query, job.push)
                job.slug = guide.slug
                await job.push({"kind": "complete", "message": "Done", "slug": guide.slug})
                async with job._cond:
                    job.status = "done"
                    job._cond.notify_all()
            except Exception as e:  # surface the reason, don't hang the browser
                job.error = f"{type(e).__name__}: {e}"
                await job.push({"kind": "error", "message": job.error})
                async with job._cond:
                    job.status = "error"
                    job._cond.notify_all()

    def summary(self, job: Job) -> dict[str, Any]:
        return {"id": job.id, "query": job.query, "status": job.status, "slug": job.slug,
                "error": job.error, "events": len(job.events)}
