import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from httpx import Request, Response
from msgspec import Raw, json

import handlers


class LlmChatDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = handlers.DB_PATH
        handlers.DB_PATH = Path(self.tempdir.name) / "harnessd.db"
        handlers.init_database()

    def tearDown(self):
        handlers.DB_PATH = self.original_db_path
        self.tempdir.cleanup()

    def request(
        self, app_id: str, prompt: str, system: str | None = None
    ) -> handlers.LlmChatRequest:
        messages = []
        if system:
            messages.append(handlers.Message(role="system", content=system))
        messages.append(handlers.Message(role="user", content=prompt))
        return handlers.LlmChatRequest(
            appID=app_id,
            model="test-model",
            messages=Raw(json.encode(messages)),
        )

    def test_context_is_chronological_and_isolated_by_app_id(self):
        first_turn = handlers._insert_prompt(self.request("app.one", "Where is Tokyo?"))
        handlers._update_completion(first_turn, "Tokyo is in Japan.", None)
        handlers._insert_prompt(self.request("app.two", "Private prompt"))
        handlers._insert_prompt(self.request("app.one", "And London?"))

        context = handlers._conversation_context("app.one")

        self.assertEqual(
            [(message.role, message.content) for message in context],
            [
                ("user", "Where is Tokyo?"),
                ("assistant", "Tokyo is in Japan."),
                ("user", "And London?"),
            ],
        )

    def test_completion_sets_reasoning_completed_and_timestamp(self):
        turn = handlers._insert_prompt(self.request("app.one", "Question"))
        handlers._update_completion(turn, "Answer", "Reasoning")

        with sqlite3.connect(handlers.DB_PATH) as db:
            row = db.execute(
                "SELECT completion, reasoning, completed, completion_ts FROM turns"
            ).fetchone()

        self.assertEqual(row[:3], ("Answer", "Reasoning", 1))
        self.assertIsInstance(row[3], int)

    def test_system_and_user_messages_share_one_turn(self):
        handlers._insert_prompt(self.request("app.one", "Ready", "Keep one city"))

        context = handlers._conversation_context("app.one")

        self.assertEqual(
            [(message.role, message.content) for message in context],
            [("system", "Keep one city"), ("user", "Ready")],
        )

    def test_legacy_text_prompt_and_clear_are_supported(self):
        with sqlite3.connect(handlers.DB_PATH) as db:
            db.execute(
                "INSERT INTO turns(appID, prompt, completed) VALUES (?, ?, 0)",
                ("app.one", '[{"role":"system","content":"literal text"}]'),
            )
        handlers._insert_prompt(self.request("app.two", "Keep me"))

        context = handlers._conversation_context("app.one")
        handlers._clear_context("app.one")

        self.assertEqual(len(context), 1)
        self.assertEqual(context[0].role, "user")
        self.assertEqual(handlers._conversation_context("app.one"), [])
        self.assertEqual(len(handlers._conversation_context("app.two")), 1)

    def test_stream_forwards_and_persists_tokens_split_across_utf8_chunks(self):
        turn = handlers._insert_prompt(self.request("app.one", "Question"))
        event = (
            'data: {"choices":[{"delta":{"content":"café"},'
            '"finish_reason":null}]}\n\ndata: [DONE]\n\n'
        ).encode()
        split = event.index("é".encode()) + 1
        response = Response(
            200,
            content=_ChunkedStream([event[:split], event[split:]]),
            request=Request("POST", "https://runner.test/v1/chat/completions"),
        )

        forwarded = asyncio.run(_collect(handlers._stream_and_persist(response, turn)))

        self.assertEqual(forwarded, event)
        with sqlite3.connect(handlers.DB_PATH) as db:
            completion, completed = db.execute(
                "SELECT completion, completed FROM turns WHERE turnID = ?", (turn,)
            ).fetchone()
        self.assertEqual((completion, completed), ("café", 1))


class _ChunkedStream:
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        pass


async def _collect(stream):
    return b"".join([chunk async for chunk in stream])


if __name__ == "__main__":
    unittest.main()
