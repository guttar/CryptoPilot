from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.database.sql_session import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="user")  # admin, user, editor
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    knowledge_bases = relationship("KnowledgeBase", back_populates="owner")
    chat_sessions = relationship("ChatSession", back_populates="user")
    assistants = relationship("Assistant", back_populates="user")
    agents = relationship("Agent", back_populates="user")
    agent_runs = relationship("AgentRun", back_populates="user", cascade="all, delete-orphan")

class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, index=True)
    kb_uid = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_public = Column(Boolean, default=False)
    vector_store_collection = Column(String, nullable=True)
    chunking_config = Column(JSON, nullable=True) # New: Store chunking strategy config
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="knowledge_bases")
    documents = relationship("KnowledgeDocument", back_populates="knowledge_base", cascade="all, delete-orphan")
    generated_qas = relationship("GeneratedQAPair", back_populates="knowledge_base", cascade="all, delete-orphan")
    # Many-to-many with Assistant via association table if needed, or JSON in Assistant

class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, index=True)
    doc_uid = Column(String, unique=True, index=True, nullable=False)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)
    status = Column(Integer, default=0)  # 0: Uploading, 1: Processing, 2: Completed, 3: Failed
    chunk_count = Column(Integer, default=0)
    chunking_config = Column(JSON, nullable=True) # Override KB config
    error_msg = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    qa_pairs = relationship("GeneratedQAPair", back_populates="document", cascade="all, delete-orphan")

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    chunk_uid = Column(String, unique=True, index=True, nullable=False)
    doc_id = Column(Integer, ForeignKey("knowledge_documents.id"), nullable=False)
    content = Column(Text, nullable=False)
    page_num = Column(Integer, nullable=True)
    vector_id = Column(String, nullable=False)  # ID in Milvus
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("KnowledgeDocument", back_populates="chunks")

class GeneratedQAPair(Base):
    __tablename__ = "generated_qa_pairs"

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False)
    doc_id = Column(Integer, ForeignKey("knowledge_documents.id"), nullable=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    qa_type = Column(String, default="single_hop")  # single_hop, multi_hop, summary, error
    status = Column(Integer, default=0)  # 0: Pending, 1: Confirmed, 2: Rejected
    created_by = Column(String, default="system")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    knowledge_base = relationship("KnowledgeBase", back_populates="generated_qas")
    document = relationship("KnowledgeDocument", back_populates="qa_pairs")

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_uid = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    assistant_id = Column(Integer, ForeignKey("assistants.id"), nullable=True)
    title = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="chat_sessions")
    assistant = relationship("Assistant", back_populates="chat_sessions")
    interactions = relationship("ChatInteraction", back_populates="session")

class ChatInteraction(Base):
    __tablename__ = "chat_interactions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True) # Optional override
    query = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    retrieved_docs = Column(JSON, nullable=True)
    metrics = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("ChatSession", back_populates="interactions")

class UploadSession(Base):
    """断点续传上传会话"""
    __tablename__ = "upload_sessions"

    id = Column(Integer, primary_key=True, index=True)
    upload_uid = Column(String(36), unique=True, index=True, nullable=False)
    filename = Column(String(255), nullable=False)
    file_hash = Column(String(64), nullable=True)  # MD5
    file_size = Column(Integer, nullable=False)
    chunk_size = Column(Integer, nullable=False)
    total_chunks = Column(Integer, nullable=False)
    received_chunks = Column(Text, nullable=True)  # JSON list of received chunk indices
    status = Column(String(20), default="uploading")  # uploading, completed, cancelled
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    knowledge_base = relationship("KnowledgeBase")
    user = relationship("User")


class EvaluationTask(Base):
    __tablename__ = "evaluation_tasks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True)
    config = Column(JSON, nullable=True)
    status = Column(Integer, default=0)  # 0: Pending, 1: Running, 2: Completed, 3: Failed, 4: DatasetGenerated
    completed_count = Column(Integer, default=0)
    total_count = Column(Integer, default=0)
    report_path = Column(String, nullable=True)
    dataset_path = Column(String, nullable=True) # New: Path to generated or uploaded dataset file
    is_custom_dataset = Column(Boolean, default=False) # New: Flag for custom upload
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    results = relationship("EvaluationResult", back_populates="task")


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("evaluation_tasks.id"), nullable=False)
    question = Column(Text, nullable=True)
    ground_truth = Column(Text, nullable=True)
    generated_answer = Column(Text, nullable=True)
    metrics = Column(JSON, nullable=True)
    latency = Column(Float, nullable=True)
    error_msg = Column(Text, nullable=True) # New: Record error reason

    task = relationship("EvaluationTask", back_populates="results")

class EvaluationDatasetItem(Base):
    __tablename__ = "evaluation_dataset_items"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("evaluation_tasks.id"), nullable=False)
    question = Column(Text, nullable=False)
    ground_truth = Column(Text, nullable=True)
    qa_type = Column(String, default="single_hop")
    doc_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Assistant(Base):
    __tablename__ = "assistants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Configuration
    llm_model = Column(String, default="qwen-max")
    temperature = Column(Float, default=0.7)
    system_prompt = Column(Text, nullable=True)
    greeting_message = Column(Text, nullable=True) # New: Opening remarks
    
    # Memory Config
    memory_config = Column(JSON, nullable=True) # e.g. {"enable": true, "window_size": 10}
    
    # RAG Config
    kb_ids = Column(JSON, nullable=True) # List of KB IDs associated
    rag_config = Column(JSON, nullable=True) # e.g. {"top_k": 5, "enable_rerank": true}
    
    # Tool/Agent Config
    tool_config = Column(JSON, nullable=True) # List of tool names or configs
    agent_ids = Column(JSON, nullable=True) # List of linked Agent IDs
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="assistants")
    chat_sessions = relationship("ChatSession", back_populates="assistant")

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String, nullable=False) # function_call, react, plan_execute
    
    # 1. 基础元配置
    # name, description, type already exist
    
    # 2. 核心能力配置
    system_prompt = Column(Text, nullable=True)
    tools_config = Column(JSON, nullable=True) # List of tools and their permissions
    knowledge_config = Column(JSON, nullable=True) # KB binding, recall strategy
    memory_config = Column(JSON, nullable=True) # Short/Long term memory settings
    
    # 3. 执行逻辑配置
    reasoning_config = Column(JSON, nullable=True) # Max steps, mode specific settings
    security_config = Column(JSON, nullable=True) # Allowed actions, safety level
    
    # 4. 输出与交互配置
    interaction_config = Column(JSON, nullable=True) # Output format, style, clarify settings
    
    # 5. 调度与部署配置
    llm_config = Column(JSON, nullable=True) # Model name, temperature, etc. (Renamed from model_config to avoid Pydantic conflict)
    execution_config = Column(JSON, nullable=True) # Timeout, retry, fallback
    
    # Legacy/Simple config field (can be kept for backward compatibility or migrated)
    config = Column(JSON, nullable=True) 
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="agents")
    runs = relationship("AgentRun", back_populates="agent", cascade="all, delete-orphan")


class AgentRun(Base):
    """一次可恢复、可审计的 Agent 执行。"""

    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    config_snapshot = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="queued", index=True)
    answer = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    tool_trace = Column(JSON, nullable=False, default=list)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    agent = relationship("Agent", back_populates="runs")
    user = relationship("User", back_populates="agent_runs")
    events = relationship(
        "AgentRunEvent",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentRunEvent.sequence",
    )


class AgentRunEvent(Base):
    """Agent 执行事件日志；sequence 用于 SSE 断线续传。"""

    __tablename__ = "agent_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_agent_run_event_sequence"),
        Index("ix_agent_run_events_run_sequence", "run_id", "sequence"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("agent_runs.id"), nullable=False)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(50), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run = relationship("AgentRun", back_populates="events")


class Note(Base):
    """笔记模型，支持富文本和Markdown内容"""
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    note_uid = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, default="未命名笔记")
    content = Column(JSON, nullable=True)  # Tiptap JSON output
    content_text = Column(Text, nullable=True)  # Plain text for search
    content_type = Column(String, default="rich_text")  # "rich_text" | "markdown"
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tags = Column(JSON, default=list)  # Tag name array
    status = Column(String, default="active")  # "active" | "archived"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", backref="notes")
    reviews = relationship("NoteReview", back_populates="note", cascade="all, delete-orphan")
    knowledge_links = relationship("NoteKnowledgeLink", back_populates="note", cascade="all, delete-orphan")


class NoteTag(Base):
    """笔记标签"""
    __tablename__ = "note_tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    color = Column(String, default="#409EFF")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", backref="note_tags")


class NoteReview(Base):
    """笔记间隔复习 (SM-2 算法)"""
    __tablename__ = "note_reviews"

    id = Column(Integer, primary_key=True, index=True)
    note_id = Column(Integer, ForeignKey("notes.id"), nullable=False, unique=True)
    review_number = Column(Integer, default=0)
    ease_factor = Column(Float, default=2.5)
    interval = Column(Integer, default=0)  # days
    repetitions = Column(Integer, default=0)
    next_review_at = Column(DateTime(timezone=True), nullable=True)
    last_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    quality_score = Column(Integer, nullable=True)  # 0-5

    note = relationship("Note", back_populates="reviews")


class NoteKnowledgeLink(Base):
    """笔记-知识库关联，用于RAG智能问答"""
    __tablename__ = "note_knowledge_links"

    id = Column(Integer, primary_key=True, index=True)
    note_id = Column(Integer, ForeignKey("notes.id"), nullable=False)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    note = relationship("Note", back_populates="knowledge_links")
    knowledge_base = relationship("KnowledgeBase")
