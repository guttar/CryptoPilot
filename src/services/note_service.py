"""笔记服务层 — 笔记管理、SM-2 间隔复习、AI 提示工程"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import or_

from src.database.models import Note, NoteReview, NoteTag, NoteKnowledgeLink, KnowledgeBase, User
from src.llm.llm_client import LLMClient
from src.settings import settings
from src.utils.logger import logger


class NoteService:
    """笔记业务逻辑服务"""

    def __init__(self, db: Session):
        self.db = db
        self.llm = LLMClient()

    # ── CRUD ──────────────────────────────────────────────────────────

    def create_note(
        self,
        user_id: int,
        title: str = "未命名笔记",
        content: Optional[dict] = None,
        content_text: Optional[str] = None,
        content_type: str = "rich_text",
        tags: Optional[List[str]] = None,
        kb_ids: Optional[List[int]] = None,
    ) -> Note:
        """创建笔记及初始复习记录"""
        note = Note(
            note_uid=str(uuid.uuid4()),
            title=title or "未命名笔记",
            content=content,
            content_text=content_text,
            content_type=content_type,
            user_id=user_id,
            tags=tags or [],
        )
        self.db.add(note)
        self.db.flush()  # get note.id

        # Initialize SM-2 review record
        review = NoteReview(
            note_id=note.id,
            next_review_at=datetime.utcnow(),  # Due immediately for first review
        )
        self.db.add(review)

        # Link knowledge bases if provided
        if kb_ids:
            for kb_id in kb_ids:
                kb = self.db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
                if kb and (kb.owner_id == user_id or kb.is_public):
                    link = NoteKnowledgeLink(note_id=note.id, kb_id=kb_id)
                    self.db.add(link)

        self.db.commit()
        self.db.refresh(note)
        return note

    def get_note(self, note_id: int, user_id: int) -> Optional[Note]:
        """获取单个笔记"""
        return self.db.query(Note).filter(
            Note.id == note_id, Note.user_id == user_id
        ).first()

    def list_notes(
        self,
        user_id: int,
        status: Optional[str] = None,
        tag: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[Note], int]:
        """列出笔记（分页、筛选）"""
        query = self.db.query(Note).filter(Note.user_id == user_id)

        if status:
            query = query.filter(Note.status == status)
        if tag:
            # JSON contains check — SQLite JSON1 extension
            query = query.filter(Note.tags.contains(tag))
        if search:
            query = query.filter(
                or_(
                    Note.title.ilike(f"%{search}%"),
                    Note.content_text.ilike(f"%{search}%"),
                )
            )

        total = query.count()
        notes = query.order_by(Note.updated_at.desc()).offset(skip).limit(limit).all()
        return notes, total

    def update_note(self, note_id: int, user_id: int, data: dict) -> Optional[Note]:
        """更新笔记"""
        note = self.get_note(note_id, user_id)
        if not note:
            return None

        for key, value in data.items():
            if hasattr(note, key) and key not in ("id", "note_uid", "user_id", "created_at"):
                setattr(note, key, value)

        note.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(note)
        return note

    def delete_note(self, note_id: int, user_id: int) -> bool:
        """删除笔记"""
        note = self.get_note(note_id, user_id)
        if not note:
            return False
        self.db.delete(note)
        self.db.commit()
        return True

    # ── Tags ──────────────────────────────────────────────────────────

    def list_tags(self, user_id: int) -> List[NoteTag]:
        """获取用户的所有标签"""
        return self.db.query(NoteTag).filter(NoteTag.user_id == user_id).all()

    def create_tag(self, user_id: int, name: str, color: str = "#409EFF") -> NoteTag:
        """创建标签"""
        tag = NoteTag(name=name, user_id=user_id, color=color)
        self.db.add(tag)
        self.db.commit()
        self.db.refresh(tag)
        return tag

    # ── Knowledge Base Links ─────────────────────────────────────────

    def get_linked_kb_ids(self, note_id: int) -> List[int]:
        """获取笔记关联的知识库 ID 列表"""
        links = self.db.query(NoteKnowledgeLink).filter(
            NoteKnowledgeLink.note_id == note_id
        ).all()
        return [link.kb_id for link in links]

    def update_kb_links(self, note_id: int, kb_ids: List[int], user_id: int) -> None:
        """更新笔记的知识库关联"""
        self.db.query(NoteKnowledgeLink).filter(
            NoteKnowledgeLink.note_id == note_id
        ).delete()

        for kb_id in kb_ids:
            kb = self.db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
            if kb and (kb.owner_id == user_id or kb.is_public):
                link = NoteKnowledgeLink(note_id=note_id, kb_id=kb_id)
                self.db.add(link)

        self.db.commit()

    # ── SM-2 Spaced Repetition ───────────────────────────────────────

    def _sm2(self, quality_score: int, review: NoteReview) -> NoteReview:
        """
        SM-2 间隔复习算法

        Args:
            quality_score: 用户自评质量 (0-5)
                0: 完全遗忘
                1: 记忆错误但看到答案后能认出
                2: 记忆错误但答案似乎熟悉
                3: 回忆困难但最终正确
                4: 回忆稍有延迟但正确
                5: 完美回忆
            review: 当前的复习记录对象

        Returns:
            更新后的复习记录
        """
        quality_score = max(0, min(5, quality_score))

        if quality_score >= 3:
            # 正确回答 — 增加间隔
            review.repetitions += 1
            if review.repetitions == 1:
                review.interval = 1
            elif review.repetitions == 2:
                review.interval = 6
            else:
                review.interval = round(review.interval * review.ease_factor)
        else:
            # 错误回答 — 重置间隔
            review.repetitions = 0
            review.interval = 1

        # 更新难度系数 (ease factor)
        new_ef = review.ease_factor + (0.1 - (5 - quality_score) * (0.08 + (5 - quality_score) * 0.02))
        review.ease_factor = max(1.3, new_ef)

        review.review_number += 1
        review.quality_score = quality_score
        review.last_reviewed_at = datetime.utcnow()
        review.next_review_at = datetime.utcnow() + timedelta(days=review.interval)

        return review

    def schedule_review(self, note_id: int, user_id: int, quality_score: int) -> Optional[dict]:
        """对笔记执行一次复习"""
        note = self.get_note(note_id, user_id)
        if not note:
            return None

        review = self.db.query(NoteReview).filter(NoteReview.note_id == note_id).first()
        if not review:
            review = NoteReview(note_id=note_id)
            self.db.add(review)
            self.db.flush()

        review = self._sm2(quality_score, review)
        self.db.commit()

        return {
            "note_id": note_id,
            "review_number": review.review_number,
            "ease_factor": review.ease_factor,
            "interval": review.interval,
            "repetitions": review.repetitions,
            "quality_score": review.quality_score,
            "last_reviewed_at": review.last_reviewed_at.isoformat() if review.last_reviewed_at else None,
            "next_review_at": review.next_review_at.isoformat() if review.next_review_at else None,
        }

    def get_review_status(self, note_id: int, user_id: int) -> Optional[dict]:
        """获取笔记的复习状态"""
        note = self.get_note(note_id, user_id)
        if not note:
            return None

        now = datetime.utcnow()
        review = self.db.query(NoteReview).filter(NoteReview.note_id == note_id).first()
        if not review:
            return {"is_due": True, "next_review_at": None, "interval": 0, "ease_factor": 2.5, "repetitions": 0}

        return {
            "is_due": review.next_review_at is not None and review.next_review_at <= now,
            "next_review_at": review.next_review_at.isoformat() if review.next_review_at else None,
            "interval": review.interval,
            "ease_factor": review.ease_factor,
            "repetitions": review.repetitions,
            "review_number": review.review_number,
            "quality_score": review.quality_score,
        }

    def get_due_notes(self, user_id: int, limit: int = 20) -> List[Note]:
        """获取当前到期的笔记"""
        now = datetime.utcnow()
        notes = (
            self.db.query(Note)
            .join(NoteReview, NoteReview.note_id == Note.id)
            .filter(
                Note.user_id == user_id,
                Note.status == "active",
                or_(
                    NoteReview.next_review_at.is_(None),
                    NoteReview.next_review_at <= now,
                ),
            )
            .order_by(NoteReview.next_review_at.asc().nullsfirst())
            .limit(limit)
            .all()
        )
        return notes

    # ── AI Inline Completion ─────────────────────────────────────────

    def get_completion_prompt(self, text_before_cursor: str, content_type: str = "rich_text") -> str:
        """构建 AI 联机补全的提示词"""
        return f"""你是一个写作助手，正在续写用户的思路。

当前文本：
{text_before_cursor}

请从光标位置自然地继续写下去。只输出续写内容（不含前置说明）。
控制在 {settings.AI_COMPLETION_MAX_TOKENS} 个 token 以内。
风格：匹配现有的语气和格式。

续写："""

    def generate_completion(self, text_before_cursor: str, content_type: str = "rich_text") -> str:
        """生成行内补全建议"""
        if len(text_before_cursor.strip()) < settings.AI_COMPLETION_TRIGGER_CHARS:
            return ""

        prompt = self.get_completion_prompt(text_before_cursor, content_type)
        try:
            completion = self.llm.generate_custom_response(
                prompt,
                system_prompt="你是一个简洁的写作助手。只输出必要的续写内容，不要重复用户已写的内容。"
            )
            return completion.strip()
        except Exception as e:
            logger.error(f"AI completion failed: {e}")
            return ""

    # ── AI Writing Assistant ─────────────────────────────────────────

    def get_writing_prompt(self, action: str, content: str, instruction: str = "") -> str:
        """构建写作助手的提示词"""
        prompts = {
            "continue": f"""你是用户的写作助手。请根据以下文本自然地续写下去，保持风格一致。

当前文本：
{content}

请续写下一段内容：""",
            "expand": f"""你是用户的写作助手。请对以下文本进行扩写，丰富细节和深度表达。

原文：
{content}

扩写后的版本：""",
            "summarize": f"""你是用户的写作助手。请为以下文本生成简洁的摘要，保留关键信息。

文本：
{content}

摘要：""",
            "custom": f"""你是用户的写作助手。

文本：
{content}

用户指令：{instruction}

结果：""",
        }
        return prompts.get(action, prompts["custom"])

    async def stream_writing(self, action: str, content: str, instruction: str = ""):
        """流式执行写作辅助操作"""
        prompt = self.get_writing_prompt(action, content, instruction)
        system_msg = "你是一个专业的写作助手。输出内容要自然、流畅、贴合上下文。"

        try:
            async for token in self.llm.generate_stream(prompt, system_prompt=system_msg):
                yield token
        except Exception as e:
            logger.error(f"AI writing stream failed: {e}")
            yield f"\n\n[生成出错: {str(e)}]"
