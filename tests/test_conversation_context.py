import unittest
import fakeredis

from src.services.memory_service import MemorySystem
from src.services.conversation_context import format_context, select_related_history


class ConversationContextTests(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis()
        self.memory = MemorySystem(self.redis)

    def add(self, session, count):
        for i in range(count):
            self.memory.add_short_term_memory(session, "user", f"message {i}")

    def test_summary_rolls_forward_without_resummarizing_recent_messages(self):
        self.add("a", 6)
        calls = []
        def summarize(previous, messages, size):
            calls.append((previous, [m["content"] for m in messages]))
            return previous + "compressed"
        context = self.memory.get_context("a", window_size=2, summarizer=summarize)
        self.assertIn("compressed", context)
        self.assertEqual(calls[0][1], [f"message {i}" for i in range(4)])
        self.memory.get_context("a", window_size=2, summarizer=summarize)
        self.assertEqual(len(calls), 1)
        self.memory.add_short_term_memory("a", "user", "new")
        self.memory.get_context("a", window_size=2, summarizer=summarize)
        self.assertEqual(calls[1], ("compressed", ["message 4"]))

    def test_failure_preserves_raw_history_for_retry(self):
        self.add("a", 6)
        def fail(*args):
            raise RuntimeError("model unavailable")
        context = self.memory.get_context("a", window_size=2, summarizer=fail)
        self.assertIn("message 5", context)
        self.assertEqual(self.redis.llen("session:a:history"), 6)

    def test_concurrent_append_is_not_lost(self):
        self.add("a", 4)
        calls = []
        def summarize(*args):
            if not calls:
                self.memory.add_short_term_memory("a", "user", "concurrent")
            calls.append(1)
            return "summary"
        context = self.memory.get_context("a", window_size=2, summarizer=summarize)
        self.assertEqual(len(calls), 2)
        self.assertIn("concurrent", context)

    def test_budget_is_bounded_and_newest_message_has_priority(self):
        context = format_context("x" * 2000, [{"role": "user", "content": "y" * 10000}], 300)
        self.assertLessEqual(len(context), 300)
        self.assertIn("yyy", context)

    def test_session_isolation_ttl_and_clear(self):
        self.add("a", 4)
        self.memory.get_context("a", window_size=2, summarizer=lambda *args: "private")
        self.assertNotIn("private", self.memory.get_context("b"))
        self.assertGreater(self.redis.ttl("session:a:summary"), 0)
        self.memory.clear_short_term_memory("a")
        self.assertEqual(self.memory.get_context("a"), "")

    def test_related_history_keeps_question_and_answer_and_excludes_unrelated_turns(self):
        history = [
            {"role": "user", "content": "TLS 1.3 key derivation"},
            {"role": "assistant", "content": "It uses HKDF"},
            {"role": "user", "content": "weather tomorrow"},
            {"role": "assistant", "content": "sunny"},
        ]
        chosen = select_related_history("TLS 1.3", history)
        self.assertEqual(chosen, history[:2])
        self.assertEqual(select_related_history("", history), [])

    def test_archived_history_can_be_recalled_after_compression(self):
        for role, text in [("user", "TLS 1.3 key derivation"), ("assistant", "HKDF"),
                           ("user", "weather"), ("assistant", "sunny")]:
            self.memory.add_short_term_memory("a", role, text)
        self.memory.get_context("a", "weather", window_size=2, summarizer=lambda *args: "short summary")
        context = self.memory.get_context("a", "TLS 1.3", window_size=2)
        self.assertIn("相关历史", context)
        self.assertIn("HKDF", context)
        self.assertNotIn("HKDF", self.memory.get_context("b", "TLS 1.3"))

    def test_related_history_supports_chinese_and_respects_context_budget(self):
        history = [{"role": "user", "content": "讨论前向保密性质"}]
        self.assertEqual(select_related_history("前向保密", history), history)
        self.assertLessEqual(len(format_context("s" * 1000, [], 256, history)), 256)
