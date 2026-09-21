from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List, Optional, Any
from pydantic import BaseModel
import json
import uuid
import asyncio

from src.database.sql_session import get_db, SessionLocal
from src.database.models import ChatSession, ChatInteraction, User, KnowledgeBase, Assistant, Agent
from src.services.rag_service import RAGService
from src.services.memory_service import MemorySystem
from src.services.assistant_agent_orchestrator import AssistantAgentOrchestrator
from src.api.dependencies import get_current_user
from src.utils.logger import logger

router = APIRouter()
rag_service = RAGService()
memory_system = MemorySystem()


def _agent_config(agent: Agent) -> dict:
    """Create an immutable configuration snapshot for an Assistant chat turn."""
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


def _resolve_assistant_config(
    assistant: Optional[Assistant],
    requested_kb_id: Optional[int],
    user_id: int,
    db: Session,
) -> tuple[dict, List[int]]:
    """Resolve only resources the current user is allowed to execute."""
    raw_kb_ids = (assistant.kb_ids or []) if assistant else ([requested_kb_id] if requested_kb_id else [])
    try:
        kb_ids = sorted({int(value) for value in raw_kb_ids})
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Knowledge base IDs must be integers") from exc

    valid_kb_ids: List[int] = []
    if kb_ids:
        valid_kb_ids = [
            row[0]
            for row in (
                db.query(KnowledgeBase.id)
                .filter(
                    KnowledgeBase.id.in_(kb_ids),
                    or_(KnowledgeBase.owner_id == user_id, KnowledgeBase.is_public.is_(True)),
                )
                .all()
            )
        ]
        denied = sorted(set(kb_ids) - set(valid_kb_ids))
        if denied:
            raise HTTPException(status_code=403, detail=f"Knowledge base access denied: {denied}")

    raw_agent_ids = (assistant.agent_ids or []) if assistant else []
    try:
        agent_ids = list(dict.fromkeys(int(value) for value in raw_agent_ids))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Agent IDs must be integers") from exc

    agents_by_id = {}
    if agent_ids:
        owned_agents = db.query(Agent).filter(Agent.id.in_(agent_ids), Agent.user_id == user_id).all()
        agents_by_id = {agent.id: agent for agent in owned_agents}
        denied = [agent_id for agent_id in agent_ids if agent_id not in agents_by_id]
        if denied:
            raise HTTPException(status_code=403, detail=f"Agent access denied: {denied}")

    config = {
        "llm_model": assistant.llm_model if assistant else "qwen-max",
        "temperature": assistant.temperature if assistant else 0.7,
        "system_prompt": assistant.system_prompt if assistant else None,
        "memory_config": assistant.memory_config if assistant else None,
        "rag_config": assistant.rag_config if assistant else None,
        "tool_config": assistant.tool_config if assistant else None,
        "agents": [
            {"id": agent_id, "name": agents_by_id[agent_id].name, "config": _agent_config(agents_by_id[agent_id])}
            for agent_id in agent_ids
        ],
    }
    return config, valid_kb_ids


class ChatRequest(BaseModel):
    """聊天请求数据模型"""
    query: str
    session_id: Optional[str] = None
    kb_id: Optional[int] = None  # Deprecated/Override
    assistant_id: Optional[int] = None  # New: Select Assistant
    top_k: int = 5


class ChatResponse(BaseModel):
    """聊天响应数据模型"""
    session_id: str
    query: str
    answer: str
    source_documents: List[Any]


class SessionOut(BaseModel):
    """会话输出数据模型"""
    id: int
    session_uid: str
    title: Optional[str]
    created_at: Any
    assistant_id: Optional[int]

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    """消息输出数据模型"""
    query: str
    answer: str
    created_at: Any
    
    class Config:
        from_attributes = True


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    处理用户聊天请求的核心接口
    
    该接口支持基于助手的对话模式，集成RAG服务和记忆系统，
    自动管理会话生命周期并保存交互历史。
    
    Args:
        request (ChatRequest): 聊天请求对象，包含查询文本、助手ID、会话ID等参数
        current_user (User): 当前登录用户，通过依赖注入获取
        db (Session): 数据库会话，通过依赖注入获取
    
    Returns:
        ChatResponse: 聊天响应对象，包含会话ID、查询文本、答案和来源文档
        
    Raises:
        HTTPException: 当助手不存在、无权限访问助手或会话时抛出404或403错误
    """
    # 解析助手配置
    assistant = None
    if request.assistant_id:
        assistant = db.query(Assistant).filter(Assistant.id == request.assistant_id).first()
        if not assistant:
             raise HTTPException(status_code=404, detail="Assistant not found")
        if assistant.user_id != current_user.id:
             raise HTTPException(status_code=403, detail="Not authorized for this assistant")
        

    assistant_config, valid_kb_ids = _resolve_assistant_config(
        assistant, request.kb_id, current_user.id, db
    )
    
    # 管理会话：创建新会话或复用现有会话
    session_uid = request.session_id
    if not session_uid:
        session_uid = str(uuid.uuid4())
        chat_session = ChatSession(
            session_uid=session_uid,
            user_id=current_user.id,
            assistant_id=request.assistant_id,
            title=request.query[:50]
        )
        db.add(chat_session)
        db.commit()
        db.refresh(chat_session)
    else:
        chat_session = db.query(ChatSession).filter(ChatSession.session_uid == session_uid).first()
        if not chat_session:
            chat_session = ChatSession(
                session_uid=session_uid,
                user_id=current_user.id,
                assistant_id=request.assistant_id,
                title=request.query[:50]
            )
            db.add(chat_session)
            db.commit()
            db.refresh(chat_session)
        
        if chat_session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to access this session")

    # 已绑定 Agent 的助手走真实 Agent 执行链；普通助手继续使用 RAG。
    if assistant_config["agents"]:
        result = await AssistantAgentOrchestrator().run(
            question=request.query,
            agents=assistant_config["agents"],
            session_id=session_uid,
            user_id=current_user.id,
        )
    else:
        result = await asyncio.to_thread(
            rag_service.query,
            query_text=request.query,
            top_k=request.top_k,
            session_id=session_uid,
            kb_ids=valid_kb_ids,
            assistant_config=assistant_config,
        )
    
    # 保存交互记录到数据库
    interaction = ChatInteraction(
        session_id=chat_session.id,
        kb_id=valid_kb_ids[0] if valid_kb_ids else None,
        query=request.query,
        answer=result["answer"],
        retrieved_docs=result.get("source_documents"),
        metrics={"agent_trace": result.get("tool_trace", [])}
    )
    db.add(interaction)
    db.commit()
    
    return ChatResponse(
        session_id=session_uid,
        query=request.query,
        answer=result["answer"],
        source_documents=result.get("source_documents", [])
    )


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    SSE 流式聊天接口

    与 POST / 返回 JSON 不同，此接口使用 Server-Sent Events 逐 token
    推送 LLM 生成内容，前端可实时展示打字机效果。
    """
    # 解析助手配置（同步，与非流式接口逻辑一致）
    assistant = None

    if request.assistant_id:
        assistant = db.query(Assistant).filter(Assistant.id == request.assistant_id).first()
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")
        if assistant.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized for this assistant")

    assistant_config, valid_kb_ids = _resolve_assistant_config(
        assistant, request.kb_id, current_user.id, db
    )

    # 管理会话
    session_uid = request.session_id
    if not session_uid:
        session_uid = str(uuid.uuid4())
        chat_session = ChatSession(
            session_uid=session_uid,
            user_id=current_user.id,
            assistant_id=request.assistant_id,
            title=request.query[:50]
        )
        db.add(chat_session)
        db.commit()
        db.refresh(chat_session)
    else:
        chat_session = db.query(ChatSession).filter(ChatSession.session_uid == session_uid).first()
        if not chat_session:
            chat_session = ChatSession(
                session_uid=session_uid,
                user_id=current_user.id,
                assistant_id=request.assistant_id,
                title=request.query[:50]
            )
            db.add(chat_session)
            db.commit()
            db.refresh(chat_session)
        if chat_session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to access this session")

    async def event_generator():
        """SSE 事件生成器：逐 token 推送，流结束后保存交互记录。"""
        full_answer = ""
        source_docs = None
        agent_trace = []
        agent_task = None

        # 立即推送 session_id，方便前端追踪新会话
        yield f"data: {json.dumps({'type': 'session_id', 'session_id': session_uid}, ensure_ascii=False)}\n\n"

        try:
            if assistant_config["agents"]:
                event_queue: asyncio.Queue = asyncio.Queue()

                async def emit(event_type: str, payload: dict) -> None:
                    await event_queue.put(
                        {"type": "agent_event", "event": event_type, "data": payload}
                    )

                agent_task = asyncio.create_task(
                    AssistantAgentOrchestrator().run(
                        question=request.query,
                        agents=assistant_config["agents"],
                        session_id=session_uid,
                        user_id=current_user.id,
                        emit=emit,
                    )
                )
                while not agent_task.done() or not event_queue.empty():
                    try:
                        event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    agent_trace.append(event)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                result = await agent_task
                full_answer = result["answer"]
                source_docs = result.get("source_documents", [])
                yield f"data: {json.dumps({'type': 'token', 'content': full_answer}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'sources', 'data': source_docs}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            else:
                async for event in rag_service.query_stream(
                    query_text=request.query,
                    top_k=request.top_k,
                    session_id=session_uid,
                    kb_ids=valid_kb_ids,
                    assistant_config=assistant_config,
                ):
                    if event["type"] == "token":
                        full_answer += event["content"]
                    elif event["type"] == "sources":
                        source_docs = event["data"]
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            if agent_task and not agent_task.done():
                agent_task.cancel()
                await asyncio.gather(agent_task, return_exceptions=True)
            raise
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            # 保存到记忆系统
            if full_answer:
                try:
                    memory_system.add_short_term_memory(session_uid, "user", request.query)
                    memory_system.add_short_term_memory(session_uid, "assistant", full_answer)
                except Exception as e:
                    logger.error(f"Failed to save memory: {e}")

                # 保存交互到数据库（使用独立会话）
                try:
                    new_db = SessionLocal()
                    interaction = ChatInteraction(
                        session_id=chat_session.id,
                        kb_id=valid_kb_ids[0] if valid_kb_ids else None,
                        query=request.query,
                        answer=full_answer,
                        retrieved_docs=source_docs or [],
                        metrics={"agent_events": agent_trace}
                    )
                    new_db.add(interaction)
                    new_db.commit()
                    new_db.close()
                except Exception as e:
                    logger.error(f"Failed to save interaction: {e}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/sessions", response_model=List[SessionOut])
def list_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取当前用户的所有聊天会话列表
    
    Args:
        current_user (User): 当前登录用户，通过依赖注入获取
        db (Session): 数据库会话，通过依赖注入获取
    
    Returns:
        List[SessionOut]: 会话列表，按创建时间降序排列
    """
    return db.query(ChatSession).filter(ChatSession.user_id == current_user.id).order_by(ChatSession.created_at.desc()).all()


@router.get("/sessions/{session_id}/messages", response_model=List[MessageOut])
def get_session_messages(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取指定会话的历史消息记录
    
    Args:
        session_id (str): 会话的唯一标识符
        current_user (User): 当前登录用户，通过依赖注入获取
        db (Session): 数据库会话，通过依赖注入获取
    
    Returns:
        List[MessageOut]: 消息列表，按创建时间升序排列
        
    Raises:
        HTTPException: 当会话不存在或无权限访问时抛出404或403错误
    """
    chat_session = db.query(ChatSession).filter(ChatSession.session_uid == session_id).first()
    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")
    if chat_session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    return db.query(ChatInteraction).filter(ChatInteraction.session_id == chat_session.id).order_by(ChatInteraction.created_at.asc()).all()


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除指定的聊天会话及其所有历史记录
    
    该操作会同时删除会话关联的交互记录和Redis中的短期记忆。
    
    Args:
        session_id (str): 要删除的会话唯一标识符
        current_user (User): 当前登录用户，通过依赖注入获取
        db (Session): 数据库会话，通过依赖注入获取
        
    Returns:
        dict: 包含删除成功消息的字典
        
    Raises:
        HTTPException: 当会话不存在或无权限访问时抛出404或403错误
    """
    chat_session = db.query(ChatSession).filter(ChatSession.session_uid == session_id).first()
    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")
    if chat_session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # 先删除会话关联的所有交互记录
    db.query(ChatInteraction).filter(ChatInteraction.session_id == chat_session.id).delete()
    db.delete(chat_session)
    db.commit()
    
    # 清除Redis中的短期记忆
    try:
        memory_system.clear_short_term_memory(session_id)
    except Exception as e:
        print(f"Error clearing memory: {e}")
    
    return {"message": "Session deleted"}


@router.delete("/sessions")
def batch_delete_sessions(
    session_ids: List[str],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    批量删除指定的聊天会话
    
    仅删除当前用户拥有权限的会话，返回实际删除的会话数量。
    
    Args:
        session_ids (List[str]): 要删除的会话唯一标识符列表
        current_user (User): 当前登录用户，通过依赖注入获取
        db (Session): 数据库会话，通过依赖注入获取
        
    Returns:
        dict: 包含实际删除会话数量的消息字典
    """
    sessions = db.query(ChatSession).filter(ChatSession.session_uid.in_(session_ids)).all()
    deleted_count = 0
    
    for session in sessions:
        if session.user_id == current_user.id:
            db.query(ChatInteraction).filter(ChatInteraction.session_id == session.id).delete()
            db.delete(session)
            deleted_count += 1
            
    db.commit()
    return {"message": f"Deleted {deleted_count} sessions"}
