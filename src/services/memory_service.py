import redis
import json
from typing import List, Dict, Any, Optional
from src.settings import settings
from src.utils.logger import logger
from src.services.long_term_memory_service import LongTermMemoryService
from src.services.conversation_context import format_context, select_related_history

class MemorySystem:
    def __init__(self, redis_client=None):
        self.redis_client = redis_client if redis_client is not None else redis.from_url(settings.REDIS_URL)
        self._long_term_service = None
        self.ttl = settings.SHORT_TERM_MEMORY_TTL
        self.history_limit = settings.MEMORY_HISTORY_LIMIT

    @property
    def long_term_service(self):
        if self._long_term_service is None:
            self._long_term_service = LongTermMemoryService()
        return self._long_term_service

    # --- Short Term Memory (Redis) ---
    
    def get_short_term_memory(self, session_id: str, limit: int = 10) -> List[Dict[str, str]]:
        """Retrieve recent conversation history from Redis."""
        key = f"session:{session_id}:history"
        try:
            # Redis lrange: 0 to limit-1 (limit elements)
            # If limit is 0, return empty
            if limit <= 0:
                return []
                
            data = self.redis_client.lrange(key, 0, limit - 1)
            # Redis stores most recent at head (lpush), so we need to reverse to get chronological order
            # Wait, lpush puts new at index 0. So index 0 is newest.
            # If we want context: "User: hi", "Assistant: hello", we want oldest first.
            # lrange(0, -1) gives [newest, ..., oldest] if lpush used.
            # Let's check add_short_term_memory: lpush.
            # So lrange returns [newest, 2nd newest, ...].
            # We should reverse it for context.
            
            messages = [json.loads(d) for d in data]
            messages.reverse() 
            return messages
        except Exception as e:
            logger.error(f"Error getting short term memory: {e}")
            return []

    def add_short_term_memory(self, session_id: str, role: str, content: str):
        """Add a new message to short term memory."""
        key = f"session:{session_id}:history"
        message = {"role": role, "content": content}
        try:
            with self.redis_client.pipeline() as pipe:
                pipe.lpush(key, json.dumps(message))
                pipe.ltrim(key, 0, self.history_limit - 1)
                pipe.expire(key, self.ttl)
                pipe.execute()
        except Exception as e:
            logger.error(f"Error adding short term memory: {e}")

    def clear_short_term_memory(self, session_id: str):
        """Clear session history."""
        key = f"session:{session_id}:history"
        self.redis_client.delete(key, f"session:{session_id}:summary", f"session:{session_id}:archive")

    def get_context(self, session_id, query="", window_size=10, max_chars=6000,
                    summarizer=None, summary_max_chars=1200, enable_summary=True,
                    relevant_history_top_k=3):
        """Compress evicted messages atomically; failure preserves the raw history."""
        window_size = min(max(int(window_size), 1), 50)
        summary_max_chars = min(max(int(summary_max_chars), 128), 4000)
        history_key = f"session:{session_id}:history"
        summary_key = f"session:{session_id}:summary"
        archive_key = f"session:{session_id}:archive"
        for _ in range(3):
            try:
                with self.redis_client.pipeline() as pipe:
                    pipe.watch(history_key, summary_key, archive_key)
                    messages = [json.loads(item) for item in pipe.lrange(history_key, 0, -1)]
                    messages.reverse()
                    raw_summary = pipe.get(summary_key) or b""
                    summary = raw_summary.decode() if isinstance(raw_summary, bytes) else raw_summary
                    older = messages[:-window_size]
                    archive = json.loads(pipe.get(archive_key) or "[]")
                    related = select_related_history(query, archive + older, relevant_history_top_k)
                    if older and enable_summary and summarizer:
                        new_summary = summarizer(summary, older, summary_max_chars)
                        if not isinstance(new_summary, str) or not new_summary.strip():
                            raise ValueError("Empty conversation summary")
                        pipe.multi()
                        pipe.set(summary_key, new_summary[:summary_max_chars], ex=self.ttl)
                        pipe.set(archive_key, json.dumps((archive + older)[-50:]), ex=self.ttl)
                        pipe.ltrim(history_key, 0, window_size - 1)
                        pipe.expire(history_key, self.ttl)
                        pipe.execute()
                        summary = new_summary[:summary_max_chars]
                    return format_context(summary, messages[-window_size:], max_chars, related)
            except redis.WatchError:
                continue
            except Exception as exc:
                logger.warning(f"Conversation compression unavailable: {exc}")
                break
        return format_context("", self.get_short_term_memory(session_id, window_size), max_chars)

    # --- Long Term Memory (Milvus) ---
    # Note: This is a simplified version using the existing Milvus setup
    # In a full implementation, we might want a separate collection for "insights"

    def add_long_term_memory(self, user_id: int, insight: str, memory_type: str = "insight"):
        """Store a non-secret insight in the isolated long-term memory collection."""
        return self.long_term_service.add(
            user_id=user_id,
            content=insight,
            memory_type=memory_type,
            metadata={"source": "memory_system"},
        )

    def retrieve_long_term_memory(self, user_id: int, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Retrieve only memories belonging to the requesting user."""
        return self.long_term_service.recall(user_id=user_id, query=query, top_k=top_k)
