"""笔记功能路由 — CRUD、间隔复习、AI 补全/写作、智能问答"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime
import json
import uuid

from src.database.sql_session import get_db, SessionLocal
from src.database.models import User, KnowledgeBase, ChatSession, ChatInteraction
from src.services.note_service import NoteService
from src.services.rag_service import RAGService
from src.services.memory_service import MemorySystem
from src.api.dependencies import get_current_user
from src.utils.logger import logger

router = APIRouter()
rag_service = RAGService()
memory_system = MemorySystem()


# ── Pydantic Schemas ─────────────────────────────────────────────────

class NoteCreate(BaseModel):
    title: str = "未命名笔记"
    content: Optional[dict] = None
    content_text: Optional[str] = None
    content_type: str = "rich_text"
    tags: List[str] = []
    kb_ids: List[int] = []


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[dict] = None
    content_text: Optional[str] = None
    content_type: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None
    kb_ids: Optional[List[int]] = None


class NoteOut(BaseModel):
    id: int
    note_uid: str
    title: str
    content: Optional[dict]
    content_text: Optional[str]
    content_type: str
    tags: List
    status: str
    created_at: datetime
    updated_at: datetime
    review_status: Optional[dict] = None
    linked_kb_ids: List[int] = []

    class Config:
        from_attributes = True


class NoteListItem(BaseModel):
    id: int
    note_uid: str
    title: str
    content_text: Optional[str]
    content_type: str
    tags: List
    status: str
    created_at: datetime
    updated_at: datetime
    is_due: bool = False

    class Config:
        from_attributes = True


class ReviewRequest(BaseModel):
    quality_score: int  # 0-5


class ReviewResponse(BaseModel):
    note_id: int
    review_number: int
    ease_factor: float
    interval: int
    repetitions: int
    quality_score: int
    last_reviewed_at: Optional[str]
    next_review_at: Optional[str]


class AICompleteRequest(BaseModel):
    text_before_cursor: str
    content_type: str = "rich_text"


class AIWriteRequest(BaseModel):
    action: str  # continue, expand, summarize, custom
    content: str
    instruction: str = ""


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


class TagCreate(BaseModel):
    name: str
    color: str = "#409EFF"


class TagOut(BaseModel):
    id: int
    name: str
    color: str

    class Config:
        from_attributes = True


# ── Helper ───────────────────────────────────────────────────────────

def _note_to_out(note, user_id: int, db: Session) -> NoteOut:
    """将 Note ORM 对象转为 NoteOut（含复习状态和 KB 链接）"""
    svc = NoteService(db)
    review_status = svc.get_review_status(note.id, user_id)
    kb_ids = svc.get_linked_kb_ids(note.id)
    return NoteOut(
        id=note.id,
        note_uid=note.note_uid,
        title=note.title,
        content=note.content,
        content_text=note.content_text,
        content_type=note.content_type,
        tags=note.tags or [],
        status=note.status,
        created_at=note.created_at,
        updated_at=note.updated_at,
        review_status=review_status,
        linked_kb_ids=kb_ids,
    )


# ── CRUD Endpoints ───────────────────────────────────────────────────

@router.get("/", response_model=dict)
def list_notes(
    status: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取笔记列表（分页、筛选）"""
    svc = NoteService(db)
    notes, total = svc.list_notes(
        user_id=current_user.id,
        status=status,
        tag=tag,
        search=search,
        skip=skip,
        limit=limit,
    )

    now = datetime.utcnow()
    items = []
    for note in notes:
        review = None
        is_due = False
        if note.reviews:
            review = note.reviews[0]
            is_due = review.next_review_at is not None and review.next_review_at <= now

        items.append(NoteListItem(
            id=note.id,
            note_uid=note.note_uid,
            title=note.title,
            content_text=note.content_text,
            content_type=note.content_type,
            tags=note.tags or [],
            status=note.status,
            created_at=note.created_at,
            updated_at=note.updated_at,
            is_due=is_due,
        ))

    return {"items": items, "total": total}


@router.post("/", response_model=NoteOut, status_code=201)
def create_note(
    request: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建新笔记"""
    svc = NoteService(db)
    note = svc.create_note(
        user_id=current_user.id,
        title=request.title,
        content=request.content,
        content_text=request.content_text,
        content_type=request.content_type,
        tags=request.tags,
        kb_ids=request.kb_ids,
    )
    return _note_to_out(note, current_user.id, db)


@router.get("/{note_id}", response_model=NoteOut)
def get_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取单个笔记详情"""
    svc = NoteService(db)
    note = svc.get_note(note_id, current_user.id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return _note_to_out(note, current_user.id, db)


@router.put("/{note_id}", response_model=NoteOut)
def update_note(
    note_id: int,
    request: NoteUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新笔记"""
    svc = NoteService(db)

    # Check ownership
    note = svc.get_note(note_id, current_user.id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")

    update_data = request.model_dump(exclude_unset=True)
    kb_ids = update_data.pop("kb_ids", None)

    note = svc.update_note(note_id, current_user.id, update_data)
    if kb_ids is not None:
        svc.update_kb_links(note_id, kb_ids, current_user.id)

    return _note_to_out(note, current_user.id, db)


@router.delete("/{note_id}")
def delete_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除笔记"""
    svc = NoteService(db)
    success = svc.delete_note(note_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return {"message": "笔记已删除"}


# ── Tags ──────────────────────────────────────────────────────────────

@router.get("/tags/list", response_model=List[TagOut])
def list_tags(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取用户的标签列表"""
    svc = NoteService(db)
    return svc.list_tags(current_user.id)


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(
    request: TagCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建标签"""
    svc = NoteService(db)
    return svc.create_tag(current_user.id, request.name, request.color)


# ── Knowledge Base Links ──────────────────────────────────────────────

@router.get("/{note_id}/kb-links", response_model=List[int])
def get_kb_links(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取笔记关联的知识库 ID 列表"""
    svc = NoteService(db)
    note = svc.get_note(note_id, current_user.id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return svc.get_linked_kb_ids(note_id)


# ── Spaced Repetition (SM-2) ─────────────────────────────────────────

@router.get("/{note_id}/review-status")
def get_review_status(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取笔记的间隔复习状态"""
    svc = NoteService(db)
    status = svc.get_review_status(note_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return status


@router.post("/{note_id}/review", response_model=ReviewResponse)
def submit_review(
    note_id: int,
    request: ReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交复习评分（SM-2 算法）"""
    if request.quality_score < 0 or request.quality_score > 5:
        raise HTTPException(status_code=400, detail="quality_score 必须在 0-5 之间")

    svc = NoteService(db)
    result = svc.schedule_review(note_id, current_user.id, request.quality_score)
    if result is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return result


@router.get("/review/due")
def get_due_notes(
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前到期的复习笔记"""
    svc = NoteService(db)
    notes = svc.get_due_notes(current_user.id, limit=limit)
    return [
        NoteListItem(
            id=n.id,
            note_uid=n.note_uid,
            title=n.title,
            content_text=n.content_text,
            content_type=n.content_type,
            tags=n.tags or [],
            status=n.status,
            created_at=n.created_at,
            updated_at=n.updated_at,
            is_due=True,
        )
        for n in notes
    ]


# ── AI Inline Completion ─────────────────────────────────────────────

@router.post("/ai/complete")
def ai_complete(
    request: AICompleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 联机补全：根据光标前的文本生成续写建议"""
    svc = NoteService(db)
    completion = svc.generate_completion(request.text_before_cursor, request.content_type)
    return {"completion": completion}


# ── AI Writing Assistant (SSE) ────────────────────────────────────────

@router.post("/ai/write")
async def ai_write(
    request: AIWriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 写作助手：续写/扩写/摘要（SSE 流式输出）"""
    valid_actions = {"continue", "expand", "summarize", "custom"}
    if request.action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"action 必须为 {valid_actions} 之一")

    svc = NoteService(db)

    async def event_generator():
        try:
            async for token in svc.stream_writing(request.action, request.content, request.instruction):
                if token:
                    yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            logger.error(f"AI write stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Smart Q&A (RAG Chat) ─────────────────────────────────────────────

@router.post("/{note_id}/chat")
async def note_chat(
    note_id: int,
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """智能问答：基于笔记关联的知识库进行 RAG 对话（SSE 流式）"""
    svc = NoteService(db)
    note = svc.get_note(note_id, current_user.id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")

    kb_ids = svc.get_linked_kb_ids(note_id)
    if not kb_ids:
        raise HTTPException(status_code=400, detail="该笔记未关联任何知识库，请先关联知识库")

    session_uid = request.session_id or str(uuid.uuid4())

    async def event_generator():
        full_answer = ""
        source_docs = None

        yield f"data: {json.dumps({'type': 'session_id', 'session_id': session_uid}, ensure_ascii=False)}\n\n"

        try:
            async for event in rag_service.query_stream(
                query_text=request.query,
                top_k=5,
                session_id=session_uid,
                kb_ids=kb_ids,
                assistant_config={
                    "system_prompt": f"用户正在编辑笔记《{note.title}》。请基于关联知识库的内容回答，并在答案中标注引用来源。",
                },
            ):
                if event["type"] == "token":
                    full_answer += event["content"]
                elif event["type"] == "sources":
                    source_docs = event["data"]
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"Note chat stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            if full_answer:
                try:
                    memory_system.add_short_term_memory(session_uid, "user", request.query)
                    memory_system.add_short_term_memory(session_uid, "assistant", full_answer)
                except Exception as e:
                    logger.error(f"Failed to save memory: {e}")

                try:
                    new_db = SessionLocal()
                    chat_session = new_db.query(ChatSession).filter(
                        ChatSession.session_uid == session_uid
                    ).first()
                    if not chat_session:
                        chat_session = ChatSession(
                            session_uid=session_uid,
                            user_id=current_user.id,
                            title=f"笔记问答: {note.title[:30]}"
                        )
                        new_db.add(chat_session)
                        new_db.commit()
                        new_db.refresh(chat_session)

                    interaction = ChatInteraction(
                        session_id=chat_session.id,
                        query=request.query,
                        answer=full_answer,
                        retrieved_docs=source_docs or [],
                        metrics={}
                    )
                    new_db.add(interaction)
                    new_db.commit()
                    new_db.close()
                except Exception as e:
                    logger.error(f"Failed to save note chat interaction: {e}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
