from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Any
from pydantic import BaseModel
import json
import uuid

from src.database.sql_session import get_db, SessionLocal
from src.database.models import ChatSession, ChatInteraction, User, KnowledgeBase, Assistant
from src.services.rag_service import RAGService
from src.services.memory_service import MemorySystem
from src.api.dependencies import get_current_user
from src.utils.logger import logger

router = APIRouter()
rag_service = RAGService()
memory_system = MemorySystem()


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
def chat(
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
    # 解析助手配置和知识库列表
    assistant = None
    kb_ids = []
    
    if request.assistant_id:
        assistant = db.query(Assistant).filter(Assistant.id == request.assistant_id).first()
        if not assistant:
             raise HTTPException(status_code=404, detail="Assistant not found")
        if assistant.user_id != current_user.id:
             raise HTTPException(status_code=403, detail="Not authorized for this assistant")
        
        kb_ids = assistant.kb_ids or []
    elif request.kb_id:
        kb_ids = [request.kb_id]
    
    # 验证知识库权限，仅保留用户有权访问的知识库
    valid_kb_ids = []
    if kb_ids:
        kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(kb_ids)).all()
        for kb in kbs:
            if kb.owner_id == current_user.id or kb.is_public:
                valid_kb_ids.append(kb.id)
    
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

    # 构建助手配置参数并调用RAG服务进行问答
    assistant_config = {
        "llm_model": assistant.llm_model if assistant else "qwen-max",
        "temperature": assistant.temperature if assistant else 0.7,
        "system_prompt": assistant.system_prompt if assistant else None,
        "memory_config": assistant.memory_config if assistant else None,
        "rag_config": assistant.rag_config if assistant else None,
        "tool_config": assistant.tool_config if assistant else None,
        "agent_ids": assistant.agent_ids if assistant else None
    }
    
    result = rag_service.query(
        query_text=request.query,
        top_k=request.top_k,
        session_id=session_uid,
        kb_ids=valid_kb_ids,
        assistant_config=assistant_config
    )
    
    # 保存交互记录到数据库
    interaction = ChatInteraction(
        session_id=chat_session.id,
        kb_id=valid_kb_ids[0] if valid_kb_ids else None,
        query=request.query,
        answer=result["answer"],
        retrieved_docs=result.get("source_documents"),
        metrics={}
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
    # 解析助手配置和知识库列表（同步，与非流式接口逻辑一致）
    assistant = None
    kb_ids = []

    if request.assistant_id:
        assistant = db.query(Assistant).filter(Assistant.id == request.assistant_id).first()
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")
        if assistant.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized for this assistant")
        kb_ids = assistant.kb_ids or []
    elif request.kb_id:
        kb_ids = [request.kb_id]

    valid_kb_ids = []
    if kb_ids:
        kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(kb_ids)).all()
        for kb in kbs:
            if kb.owner_id == current_user.id or kb.is_public:
                valid_kb_ids.append(kb.id)

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

    assistant_config = {
        "llm_model": assistant.llm_model if assistant else "qwen-max",
        "temperature": assistant.temperature if assistant else 0.7,
        "system_prompt": assistant.system_prompt if assistant else None,
        "memory_config": assistant.memory_config if assistant else None,
        "rag_config": assistant.rag_config if assistant else None,
        "tool_config": assistant.tool_config if assistant else None,
        "agent_ids": assistant.agent_ids if assistant else None
    }

    async def event_generator():
        """SSE 事件生成器：逐 token 推送，流结束后保存交互记录。"""
        full_answer = ""
        source_docs = None

        # 立即推送 session_id，方便前端追踪新会话
        yield f"data: {json.dumps({'type': 'session_id', 'session_id': session_uid}, ensure_ascii=False)}\n\n"

        try:
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
                        metrics={}
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
