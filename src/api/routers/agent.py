import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from src.database.sql_session import get_db
from src.database.models import Agent, AgentRun, AgentRunEvent, KnowledgeBase, User
from src.api.dependencies import get_current_user
from src.services.agent_service import AgentService
from src.services.agent_run_manager import TERMINAL_STATUSES, agent_run_manager
from src.settings import settings

router = APIRouter()

class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    type: str = "function_call"
    
    # New Config Fields
    system_prompt: Optional[str] = None
    tools_config: Optional[dict] = None
    knowledge_config: Optional[dict] = None
    memory_config: Optional[dict] = None
    reasoning_config: Optional[dict] = None
    security_config: Optional[dict] = None
    interaction_config: Optional[dict] = None
    llm_config: Optional[dict] = None
    execution_config: Optional[dict] = None
    
    # Legacy
    config: Optional[dict] = {}

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    
    system_prompt: Optional[str] = None
    tools_config: Optional[dict] = None
    knowledge_config: Optional[dict] = None
    memory_config: Optional[dict] = None
    reasoning_config: Optional[dict] = None
    security_config: Optional[dict] = None
    interaction_config: Optional[dict] = None
    llm_config: Optional[dict] = None
    execution_config: Optional[dict] = None
    
    config: Optional[dict] = None

class AgentOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    type: str
    
    system_prompt: Optional[str]
    tools_config: Optional[dict]
    knowledge_config: Optional[dict]
    memory_config: Optional[dict]
    reasoning_config: Optional[dict]
    security_config: Optional[dict]
    interaction_config: Optional[dict]
    llm_config: Optional[dict]
    execution_config: Optional[dict]
    
    config: Optional[dict]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class AgentRunIn(BaseModel):
    question: str

class AgentRunOut(BaseModel):
    answer: str
    tool_trace: List[dict]


class DurableAgentRunIn(BaseModel):
    question: str


class DurableAgentRunOut(BaseModel):
    id: str
    agent_id: int
    question: str
    status: str
    answer: Optional[str] = None
    error: Optional[str] = None
    tool_trace: List[dict] = Field(default_factory=list)
    cancel_requested: bool
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AgentRunEventOut(BaseModel):
    sequence: int
    event_type: str
    payload: dict
    created_at: datetime

    class Config:
        from_attributes = True


def _agent_config(agent: Agent) -> dict:
    """Freeze the configuration used by a run for reproducibility."""
    return {
        "system_prompt": agent.system_prompt,
        "tools_config": agent.tools_config or {},
        "knowledge_config": agent.knowledge_config or {},
        "memory_config": agent.memory_config or {},
        "reasoning_config": agent.reasoning_config or {},
        "security_config": agent.security_config or {},
        "interaction_config": agent.interaction_config or {},
        "llm_config": agent.llm_config or {},
        "execution_config": agent.execution_config or {},
    }


def _owned_run(run_id: str, user_id: int, db: Session) -> AgentRun:
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return run


def _validate_knowledge_access(knowledge_config: Optional[dict], user_id: int, db: Session) -> None:
    """Reject forged KB IDs before they can reach the Milvus filter."""
    if not knowledge_config:
        return
    raw_ids = knowledge_config.get("kb_ids") or []
    try:
        kb_ids = sorted({int(value) for value in raw_ids})
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="knowledge_config.kb_ids must contain integers") from exc
    if not kb_ids:
        return
    accessible_ids = {
        row[0]
        for row in (
            db.query(KnowledgeBase.id)
            .filter(
                KnowledgeBase.id.in_(kb_ids),
                or_(KnowledgeBase.owner_id == user_id, KnowledgeBase.is_public.is_(True)),
            )
            .all()
        )
    }
    denied = sorted(set(kb_ids) - accessible_ids)
    if denied:
        raise HTTPException(status_code=403, detail=f"Knowledge base access denied: {denied}")

@router.post("/", response_model=AgentOut)
def create_agent(
    agent_in: AgentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    _validate_knowledge_access(agent_in.knowledge_config, current_user.id, db)
    agent = Agent(
        name=agent_in.name,
        description=agent_in.description,
        type=agent_in.type,
        user_id=current_user.id,
        
        system_prompt=agent_in.system_prompt,
        tools_config=agent_in.tools_config,
        knowledge_config=agent_in.knowledge_config,
        memory_config=agent_in.memory_config,
        reasoning_config=agent_in.reasoning_config,
        security_config=agent_in.security_config,
        interaction_config=agent_in.interaction_config,
        llm_config=agent_in.llm_config,
        execution_config=agent_in.execution_config,
        
        config=agent_in.config
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent

@router.get("/", response_model=List[AgentOut])
def list_agents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Agent).filter(Agent.user_id == current_user.id).all()

@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return agent

@router.put("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: int,
    agent_in: AgentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    update_data = agent_in.dict(exclude_unset=True)
    if "knowledge_config" in update_data:
        _validate_knowledge_access(update_data["knowledge_config"], current_user.id, db)
    for field, value in update_data.items():
        setattr(agent, field, value)
        
    db.commit()
    db.refresh(agent)
    return agent

@router.delete("/{agent_id}")
def delete_agent(
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    db.delete(agent)
    db.commit()
    return {"message": "Agent deleted"}

@router.post("/{agent_id}/run", response_model=AgentRunOut)
async def run_agent(
    agent_id: int,
    request: AgentRunIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Execute an Agent and return both its answer and each tool result."""
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.user_id == current_user.id,
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="Question cannot be empty")
    _validate_knowledge_access(agent.knowledge_config, current_user.id, db)

    try:
        timeout_seconds = min(
            max(int((agent.execution_config or {}).get("timeout", 60)), 1),
            settings.AGENT_MAX_TIMEOUT_SECONDS,
        )
        async with asyncio.timeout(timeout_seconds):
            return await AgentService().run(request.question, _agent_config(agent))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Agent execution timed out") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{agent_id}/runs", response_model=DurableAgentRunOut, status_code=status.HTTP_202_ACCEPTED)
async def create_agent_run(
    agent_id: int,
    request: DurableAgentRunIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a durable execution and schedule it without blocking the request."""
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.user_id == current_user.id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="Question cannot be empty")
    _validate_knowledge_access(agent.knowledge_config, current_user.id, db)

    run = AgentRun(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        user_id=current_user.id,
        question=request.question.strip(),
        config_snapshot=_agent_config(agent),
        status="queued",
        tool_trace=[],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    agent_run_manager.start(run.id)
    return run


@router.get("/{agent_id}/runs", response_model=List[DurableAgentRunOut])
def list_agent_runs(
    agent_id: int,
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.user_id == current_user.id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return (
        db.query(AgentRun)
        .filter(AgentRun.agent_id == agent_id, AgentRun.user_id == current_user.id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/executions/{run_id}", response_model=DurableAgentRunOut)
def get_agent_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _owned_run(run_id, current_user.id, db)


@router.get("/executions/{run_id}/events", response_model=List[AgentRunEventOut])
def list_agent_run_events(
    run_id: str,
    after: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _owned_run(run_id, current_user.id, db)
    return (
        db.query(AgentRunEvent)
        .filter(AgentRunEvent.run_id == run_id, AgentRunEvent.sequence > after)
        .order_by(AgentRunEvent.sequence.asc())
        .limit(500)
        .all()
    )


@router.get("/executions/{run_id}/stream")
async def stream_agent_run(
    run_id: str,
    request: Request,
    after: int = Query(0, ge=0),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replay persisted events and continue streaming new events via SSE."""
    _owned_run(run_id, current_user.id, db)
    cursor = after
    if last_event_id:
        try:
            cursor = max(cursor, int(last_event_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer")

    async def event_generator():
        nonlocal cursor
        terminal_idle_polls = 0
        keepalive_ticks = 0
        while True:
            if await request.is_disconnected():
                return

            def load_batch():
                from src.database.sql_session import SessionLocal

                with SessionLocal() as stream_db:
                    stream_run = stream_db.query(AgentRun).filter(AgentRun.id == run_id).first()
                    events = (
                        stream_db.query(AgentRunEvent)
                        .filter(AgentRunEvent.run_id == run_id, AgentRunEvent.sequence > cursor)
                        .order_by(AgentRunEvent.sequence.asc())
                        .limit(100)
                        .all()
                    )
                    return (
                        stream_run.status if stream_run else "failed",
                        [
                            {
                                "sequence": item.sequence,
                                "event_type": item.event_type,
                                "payload": item.payload,
                            }
                            for item in events
                        ],
                    )

            run_status, events = await asyncio.to_thread(load_batch)
            if events:
                terminal_idle_polls = 0
                for event in events:
                    cursor = event["sequence"]
                    data = json.dumps(event["payload"], ensure_ascii=False, default=str)
                    yield f"id: {cursor}\nevent: {event['event_type']}\ndata: {data}\n\n"
            elif run_status in TERMINAL_STATUSES:
                terminal_idle_polls += 1
                # The terminal status and its terminal event are committed in
                # separate transactions; allow one poll for the event to land.
                if terminal_idle_polls >= 2:
                    return

            keepalive_ticks += 1
            if keepalive_ticks >= max(int(15 / settings.AGENT_SSE_POLL_INTERVAL), 1):
                keepalive_ticks = 0
                yield ": keep-alive\n\n"
            await asyncio.sleep(settings.AGENT_SSE_POLL_INTERVAL)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/executions/{run_id}/cancel", response_model=DurableAgentRunOut)
async def cancel_agent_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _owned_run(run_id, current_user.id, db)
    if run.status not in TERMINAL_STATUSES:
        await agent_run_manager.cancel(run_id)
        db.expire_all()
        run = _owned_run(run_id, current_user.id, db)
    return run
