from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Body
from sqlalchemy.orm import Session
from typing import List, Optional, Any, Dict
import json
import shutil
import os
import re
from datetime import datetime
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, FileResponse
import io

from src.database.sql_session import get_db
from src.database.models import KnowledgeBase, KnowledgeDocument, User, DocumentChunk, GeneratedQAPair, UploadSession
from src.utils.security import create_access_token
from src.settings import settings
from src.api.dependencies import get_current_user
from src.services.qa_generator import qa_generator
from src.worker.tasks import process_document_task
from src.services.storage import storage_service
from src.utils.preview_utils import get_preview_response
from src.utils.upload_chunk_storage import (save_chunk, assemble_file, cleanup_upload,
                                            get_missing_chunks, mark_chunk_received)

router = APIRouter()

# --- Pydantic Models ---

class KBCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_public: bool = False
    chunking_config: Optional[Dict[str, Any]] = None # e.g. {"method": "recursive", "chunk_size": 300, "chunk_overlap": 50}

class KBUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None
    chunking_config: Optional[Dict[str, Any]] = None

class KBOut(BaseModel):
    id: int
    kb_uid: str
    name: str
    description: Optional[str]
    is_public: bool
    chunking_config: Optional[Dict[str, Any]]
    created_at: datetime
    owner_id: int
    
    class Config:
        from_attributes = True

class DocumentOut(BaseModel):
    id: int
    doc_uid: str
    filename: str
    status: int
    chunk_count: int
    file_size: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class QAPairOut(BaseModel):
    id: int
    question: str
    answer: str
    qa_type: str
    created_at: Any
    
    class Config:
        from_attributes = True

class QAPairCreate(BaseModel):
    question: str
    answer: str
    qa_type: str = "single_hop"
    
class QAPairUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    qa_type: Optional[str] = None
    status: Optional[int] = None

class ChunkOut(BaseModel):
    id: int
    content: str
    page_num: Optional[int]
    
    class Config:
        from_attributes = True

def sanitize_filename(filename: str) -> str:
    # Remove dangerous characters
    # Keep alphanumeric, dot, dash, underscore, and chinese characters
    # Simplified regex
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    return filename

# --- Endpoints ---

@router.post("/", response_model=KBOut)
def create_knowledge_base(
    kb_in: KBCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    import uuid
    kb = KnowledgeBase(
        kb_uid=str(uuid.uuid4()),
        name=kb_in.name,
        description=kb_in.description,
        is_public=kb_in.is_public,
        chunking_config=kb_in.chunking_config,
        owner_id=current_user.id
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb

@router.get("/", response_model=List[KBOut])
def list_knowledge_bases(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Return user's KBs and public KBs
    # For now just user's
    return db.query(KnowledgeBase).filter(KnowledgeBase.owner_id == current_user.id).all()

@router.delete("/{kb_id}")
def delete_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Logic to delete KB:
    # 1. Delete Documents (and chunks)
    # 2. Delete generated QAs
    # 3. Delete KB
    # Note: Vector DB deletion is harder, might need to delete by kb_id if Milvus supports it
    
    db.delete(kb) # Cascading delete should be configured in DB, or manual
    # For simplicity, we assume models have cascade or we leave orphans for now
    db.commit()
    return {"message": "Knowledge Base deleted"}

@router.get("/{kb_id}", response_model=KBOut)
def get_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    if kb.owner_id != current_user.id and not kb.is_public:
         raise HTTPException(status_code=403, detail="Not authorized")
    return kb

@router.put("/{kb_id}", response_model=KBOut)
def update_knowledge_base(
    kb_id: int,
    kb_in: KBUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if kb_in.name is not None:
        kb.name = kb_in.name
    if kb_in.description is not None:
        kb.description = kb_in.description
    if kb_in.is_public is not None:
        kb.is_public = kb_in.is_public
    if kb_in.chunking_config is not None:
        kb.chunking_config = kb_in.chunking_config
        
    db.commit()
    db.refresh(kb)
    return kb

@router.post("/{kb_id}/upload")
def upload_document(
    kb_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    if kb.owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized")

    import uuid
    doc_uid = str(uuid.uuid4())
    safe_filename = sanitize_filename(file.filename)
    file_path = settings.UPLOAD_DIR / f"{doc_uid}_{safe_filename}"
    
    # Ensure directory exists (again, to be safe)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    
    try:
        # Use absolute path explicitly
        abs_file_path = file_path.resolve()
        
        with open(abs_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        if not os.path.exists(abs_file_path):
             raise Exception("File saved but not found on disk immediately.")
             
        # Try to upload to MinIO with correct content type and filename in metadata
        try:
            object_name = f"{doc_uid}_{safe_filename}"
            with open(abs_file_path, "rb") as f:
                content = f.read()
                # MinIO put_object supports metadata for Content-Disposition but presigned URL overrides it usually
                # But we can try setting content_type correctly
                storage_service.upload_file(object_name, content, file.content_type)
        except Exception as e:
            # Log error but don't fail the upload entirely? 
            # Or fail it because preview is required?
            # User wants preview, so maybe we should ensure it works.
            # But core functionality is RAG, so local file is more important.
            # Let's log and proceed, but maybe add a warning.
            print(f"Failed to upload to MinIO: {e}")
             
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
        
    doc = KnowledgeDocument(
        doc_uid=doc_uid,
        kb_id=kb.id,
        filename=safe_filename,
        file_path=str(abs_file_path), # Store absolute path
        file_type=safe_filename.split('.')[-1],
        file_size=os.path.getsize(abs_file_path),
        chunk_count=0, # Initialize chunk count
        status=0 # Uploading
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    # Trigger Celery task
    task = process_document_task.delay(doc.id)
    
    return {"message": "File uploaded successfully", "doc_id": doc.id, "task_id": task.id}


# --- Resumable Upload (断点续传) ---

class UploadInitRequest(BaseModel):
    filename: str
    file_size: int
    file_hash: Optional[str] = None
    chunk_size: int = 5 * 1024 * 1024  # 5MB default


class UploadInitResponse(BaseModel):
    upload_id: str
    chunk_size: int
    total_chunks: int
    received_chunks: List[int]
    resumed: bool


class UploadChunkResponse(BaseModel):
    chunk_index: int
    received: bool
    received_chunks: List[int]


class UploadStatusResponse(BaseModel):
    upload_id: str
    filename: str
    file_hash: Optional[str]
    file_size: int
    chunk_size: int
    total_chunks: int
    received_chunks: List[int]
    missing_chunks: List[int]
    status: str


@router.post("/{kb_id}/uploads/init", response_model=UploadInitResponse)
def init_upload(
    kb_id: int,
    body: UploadInitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """初始化断点续传会话。如果已存在相同 hash+filename 的未完成会话则恢复。"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(404, detail="Knowledge Base not found")
    if kb.owner_id != current_user.id:
        raise HTTPException(403, detail="Not authorized")

    total_chunks = max(1, (body.file_size + body.chunk_size - 1) // body.chunk_size)
    import uuid
    upload_uid = str(uuid.uuid4())
    resumed = False

    # 尝试恢复已有会话（相同 hash 且未完成）
    existing = None
    if body.file_hash:
        existing = db.query(UploadSession).filter(
            UploadSession.file_hash == body.file_hash,
            UploadSession.filename == body.filename,
            UploadSession.kb_id == kb_id,
            UploadSession.user_id == current_user.id,
            UploadSession.status == "uploading",
        ).order_by(UploadSession.created_at.desc()).first()

    if existing:
        upload_uid = existing.upload_uid
        resumed = True
        received = json.loads(existing.received_chunks or "[]")
        return UploadInitResponse(
            upload_id=upload_uid,
            chunk_size=existing.chunk_size,
            total_chunks=existing.total_chunks,
            received_chunks=sorted(received),
            resumed=True,
        )

    # 创建新会话
    session = UploadSession(
        upload_uid=upload_uid,
        filename=body.filename,
        file_hash=body.file_hash,
        file_size=body.file_size,
        chunk_size=body.chunk_size,
        total_chunks=total_chunks,
        received_chunks="[]",
        status="uploading",
        kb_id=kb_id,
        user_id=current_user.id,
    )
    db.add(session)
    db.commit()

    return UploadInitResponse(
        upload_id=upload_uid,
        chunk_size=body.chunk_size,
        total_chunks=total_chunks,
        received_chunks=[],
        resumed=False,
    )


@router.post("/{kb_id}/uploads/{upload_id}/chunk", response_model=UploadChunkResponse)
def upload_chunk(
    kb_id: int,
    upload_id: str,
    chunk_index: int = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传单个分片。支持重复上传（幂等）。"""
    session = db.query(UploadSession).filter(
        UploadSession.upload_uid == upload_id,
        UploadSession.kb_id == kb_id,
        UploadSession.status == "uploading",
    ).first()
    if not session:
        raise HTTPException(404, detail="Upload session not found")
    if session.user_id != current_user.id:
        raise HTTPException(403, detail="Not authorized")
    if chunk_index < 0 or chunk_index >= session.total_chunks:
        raise HTTPException(400, detail=f"Invalid chunk index {chunk_index}")

    # 幂等：已接收则直接返回
    received = json.loads(session.received_chunks or "[]")
    if chunk_index in received:
        return UploadChunkResponse(
            chunk_index=chunk_index,
            received=True,
            received_chunks=sorted(received),
        )

    # 保存分片
    data = file.file.read()
    save_chunk(upload_id, chunk_index, data)

    # 更新会话
    session.received_chunks = mark_chunk_received(session.received_chunks, chunk_index)
    db.commit()

    return UploadChunkResponse(
        chunk_index=chunk_index,
        received=True,
        received_chunks=sorted(json.loads(session.received_chunks)),
    )


@router.get("/{kb_id}/uploads/{upload_id}", response_model=UploadStatusResponse)
def get_upload_status(
    kb_id: int,
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询上传进度。"""
    session = db.query(UploadSession).filter(
        UploadSession.upload_uid == upload_id,
        UploadSession.kb_id == kb_id,
    ).first()
    if not session:
        raise HTTPException(404, detail="Upload session not found")
    if session.user_id != current_user.id:
        raise HTTPException(403, detail="Not authorized")

    received = json.loads(session.received_chunks or "[]")
    missing = get_missing_chunks(session.received_chunks, session.total_chunks)

    return UploadStatusResponse(
        upload_id=session.upload_uid,
        filename=session.filename,
        file_hash=session.file_hash,
        file_size=session.file_size,
        chunk_size=session.chunk_size,
        total_chunks=session.total_chunks,
        received_chunks=sorted(received),
        missing_chunks=missing,
        status=session.status,
    )


@router.post("/{kb_id}/uploads/{upload_id}/complete")
def complete_upload(
    kb_id: int,
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """完成上传：合并分片、创建文档记录、触发 Celery 处理。"""
    session = db.query(UploadSession).filter(
        UploadSession.upload_uid == upload_id,
        UploadSession.kb_id == kb_id,
        UploadSession.status == "uploading",
    ).first()
    if not session:
        raise HTTPException(404, detail="Upload session not found")
    if session.user_id != current_user.id:
        raise HTTPException(403, detail="Not authorized")

    # 检查所有分片是否齐全
    received = json.loads(session.received_chunks or "[]")
    missing = sorted(set(range(session.total_chunks)) - set(received))
    if missing:
        raise HTTPException(400, detail=f"Missing chunks: {missing}")

    # 合并分片
    import uuid
    doc_uid = str(uuid.uuid4())
    safe_filename = sanitize_filename(session.filename)
    file_path = settings.UPLOAD_DIR / f"{doc_uid}_{safe_filename}"
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    assemble_file(upload_id, session.total_chunks, file_path)

    # 上传到 MinIO（不影响主流程）
    abs_file_path = file_path.resolve()
    try:
        object_name = f"{doc_uid}_{safe_filename}"
        with open(abs_file_path, "rb") as f:
            content = f.read()
            storage_service.upload_file(object_name, content, safe_filename.split('.')[-1])
    except Exception as e:
        print(f"MinIO upload failed: {e}")

    # 创建文档记录
    doc = KnowledgeDocument(
        doc_uid=doc_uid,
        kb_id=kb_id,
        filename=safe_filename,
        file_path=str(abs_file_path),
        file_type=safe_filename.split('.')[-1],
        file_size=session.file_size,
        status=0,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 标记会话完成
    session.status = "completed"
    session.received_chunks = json.dumps(sorted(received))
    db.commit()

    # 清理分片文件
    cleanup_upload(upload_id)

    # 触发 Celery 处理
    task = process_document_task.delay(doc.id)

    return {"message": "Upload completed", "doc_id": doc.id, "task_id": task.id}


@router.delete("/{kb_id}/uploads/{upload_id}")
def cancel_upload(
    kb_id: int,
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取消上传，清理分片文件和会话记录。"""
    session = db.query(UploadSession).filter(
        UploadSession.upload_uid == upload_id,
        UploadSession.kb_id == kb_id,
    ).first()
    if not session:
        raise HTTPException(404, detail="Upload session not found")
    if session.user_id != current_user.id:
        raise HTTPException(403, detail="Not authorized")

    session.status = "cancelled"
    db.commit()

    cleanup_upload(upload_id)
    db.delete(session)
    db.commit()

    return {"message": "Upload cancelled"}

@router.post("/documents/batch-retry")
def batch_retry_documents(
    doc_ids: List[int],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(doc_ids)).all()
    restarted = []
    for doc in docs:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
        if kb and kb.owner_id == current_user.id:
            doc.status = 0
            doc.error_msg = None
            db.commit()
            process_document_task.delay(doc.id)
            restarted.append(doc.id)
            
    return {"message": f"Restarted {len(restarted)} documents"}

@router.delete("/documents/batch-delete")
def batch_delete_documents(
    doc_ids: List[int],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(doc_ids)).all()
    deleted = 0
    for doc in docs:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
        if kb and kb.owner_id == current_user.id:
            # Delete file
            if os.path.exists(doc.file_path):
                try:
                    os.remove(doc.file_path)
                except:
                    pass
            db.delete(doc)
            deleted += 1
            
    db.commit()
    return {"message": f"Deleted {deleted} documents"}

@router.post("/documents/{doc_id}/retry")
def retry_document(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if not kb or kb.owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized")
         
    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=400, detail="Original file not found on server")

    # Reset status
    doc.status = 0
    doc.error_msg = None
    db.commit()
    
    task = process_document_task.delay(doc.id)
    return {"message": "Retry started", "task_id": task.id}

@router.get("/{kb_id}/documents", response_model=List[DocumentOut])
def list_documents(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    
    return db.query(KnowledgeDocument).filter(KnowledgeDocument.kb_id == kb_id).all()

@router.post("/documents/{doc_id}/generate-qa", response_model=List[QAPairOut])
def generate_qa_for_document(
    doc_id: int,
    num_pairs: int = 5,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check permission
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    # Fetch chunks to get text
    chunks = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).limit(10).all()
    if not chunks:
        # Fallback to reading file if no chunks (e.g. text file not yet processed)
        # But usually we process first.
        # For this demo, let's just use a placeholder text if empty
        combined_text = f"Document content for {doc.filename}"
    else:
        combined_text = "\n".join([c.content for c in chunks])
    
    # Use QA Generator
    pairs = qa_generator.generate_qa_pairs(combined_text, num_pairs)
    
    saved_pairs = []
    for p in pairs:
        qa = GeneratedQAPair(
            kb_id=kb.id,
            doc_id=doc.id,
            question=p.get("question", ""),
            answer=p.get("answer", ""),
            qa_type="single_hop",
            status=0 # Pending
        )
        db.add(qa)
        saved_pairs.append(qa)
        
    db.commit()
    for qa in saved_pairs:
        db.refresh(qa)
        
    return saved_pairs

@router.post("/documents/{doc_id}/qa-pairs", response_model=QAPairOut)
def create_qa_pair(
    doc_id: int,
    qa_in: QAPairCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    qa = GeneratedQAPair(
        kb_id=kb.id,
        doc_id=doc.id,
        question=qa_in.question,
        answer=qa_in.answer,
        qa_type=qa_in.qa_type,
        status=1, # Confirmed since manually created
        created_by=current_user.username
    )
    db.add(qa)
    db.commit()
    db.refresh(qa)
    return qa

@router.put("/qa-pairs/{qa_id}", response_model=QAPairOut)
def update_qa_pair(
    qa_id: int,
    qa_in: QAPairUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    qa = db.query(GeneratedQAPair).filter(GeneratedQAPair.id == qa_id).first()
    if not qa:
        raise HTTPException(status_code=404, detail="QA Pair not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == qa.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    if qa_in.question is not None:
        qa.question = qa_in.question
    if qa_in.answer is not None:
        qa.answer = qa_in.answer
    if qa_in.qa_type is not None:
        qa.qa_type = qa_in.qa_type
    if qa_in.status is not None:
        qa.status = qa_in.status
        
    db.commit()
    db.refresh(qa)
    return qa

@router.delete("/qa-pairs/{qa_id}")
def delete_qa_pair(
    qa_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    qa = db.query(GeneratedQAPair).filter(GeneratedQAPair.id == qa_id).first()
    if not qa:
        raise HTTPException(status_code=404, detail="QA Pair not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == qa.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    db.delete(qa)
    db.commit()
    return {"message": "QA Pair deleted"}

@router.get("/documents/{doc_id}/qa-pairs/download")
def download_qa_pairs(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    qa_pairs = db.query(GeneratedQAPair).filter(GeneratedQAPair.doc_id == doc_id).all()
    
    # Generate Markdown content
    content = f"# QA Pairs for {doc.filename}\n\n"
    for i, qa in enumerate(qa_pairs, 1):
        content += f"## Question {i} ({qa.qa_type})\n\n"
        content += f"**Q:** {qa.question}\n\n"
        content += f"**A:** {qa.answer}\n\n"
        content += "---\n\n"
        
    # Create a stream
    stream = io.StringIO(content)
    
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/markdown")
    response.headers["Content-Disposition"] = f"attachment; filename=qa_pairs_{doc.filename}.md"
    return response

@router.get("/documents/{doc_id}/chunks", response_model=List[ChunkOut])
def get_document_chunks(
    doc_id: int,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    return db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).limit(limit).all()

@router.post("/documents/{doc_id}/reprocess")
def reprocess_document(
    doc_id: int,
    config: Optional[Dict[str, Any]] = Body(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized")
         
    if config:
        doc.chunking_config = config
    
    doc.status = 0 # Reset status to pending
    doc.error_msg = None
    db.commit()
    
    process_document_task.delay(doc.id)
    return {"message": "Reprocessing started", "doc_id": doc.id}

@router.get("/documents/{doc_id}/preview")
def preview_document(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    file_path = doc.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on server")
        
    return get_preview_response(file_path, doc.file_type)

@router.get("/documents/{doc_id}/qa-pairs", response_model=List[QAPairOut])
def get_document_qa_pairs(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    return db.query(GeneratedQAPair).filter(GeneratedQAPair.doc_id == doc_id).all()
