import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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

    def request(self, app_id: str, prompt: str) -> handlers.LlmChatRequest:
        return handlers.LlmChatRequest(
            appID=app_id,
            model="test-model",
            messages=Raw(json.encode([handlers.Message(role="user", content=prompt)])),
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

        forwarded = asyncio.run(_collect(handlers._stream_chat(response, turn)))

        self.assertEqual(forwarded, event)
        with sqlite3.connect(handlers.DB_PATH) as db:
            completion, completed = db.execute(
                "SELECT completion, completed FROM turns WHERE turnID = ?", (turn,)
            ).fetchone()
        self.assertEqual((completion, completed), ("café", 1))

    def test_tool_schema_calls_results_and_foreign_keys_are_persisted(self):
        schema = [{"type": "function", "function": {"name": "get_location"}}]
        initial = handlers.LlmToolsRequest(
            appID="app.one",
            model="test-model",
            messages=Raw(json.encode([handlers.Message(role="user", content="Weather?")])),
            tools=Raw(json.encode(schema)),
        )
        turn = handlers._prepare_tools_turn(initial)
        call = handlers.OpenAIToolCall(
            id="call-1",
            function=handlers.OpenAIFunction(name="get_location", arguments="{}"),
        )
        handlers._record_calls(turn, [call])
        encoded_call = json.decode(json.encode(call))
        self.assertEqual(encoded_call["type"], "function")
        follow_up = handlers.LlmToolsRequest(
            appID="app.one",
            turnID=turn,
            model="test-model",
            messages=Raw(json.encode([
                handlers.Message(role="tool", content="latitude: 42, longitude: -83",
                                 tool_call_id="call-1")
            ])),
        )
        handlers._prepare_tools_turn(follow_up)

        context = handlers._tools_context("app.one", turn)
        with sqlite3.connect(handlers.DB_PATH) as db:
            row = db.execute(
                "SELECT idx, name, arguments, result, result_ts FROM calls WHERE id = 'call-1'"
            ).fetchone()

        self.assertEqual(row[:4], (0, "get_location", "{}",
                                  "latitude: 42, longitude: -83"))
        self.assertIsInstance(row[4], int)
        self.assertEqual([message.role for message in context], ["user", "assistant", "tool"])
        self.assertEqual(len(handlers._tool_schemas("app.one")), 2)

    def test_tool_call_delta_arguments_are_reassembled(self):
        parts = {}
        first = json.decode(
            b'{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1",'
            b'"function":{"name":"get_weather","arguments":"{\\\"latitude\\\":\\\"42"}}]}}]}',
            type=handlers.OpenAIResponse,
        )
        second = json.decode(
            b'{"choices":[{"delta":{"tool_calls":[{"index":0,'
            b'"function":{"arguments":"\\\",\\\"longitude\\\":\\\"-83\\\"}"}}]}}]}',
            type=handlers.OpenAIResponse,
        )

        self.assertTrue(handlers._accumulate_tool_deltas(first, parts))
        self.assertTrue(handlers._accumulate_tool_deltas(second, parts))
        self.assertEqual(parts[0], {
            "id": "call-1",
            "name": "get_weather",
            "arguments": '{"latitude":"42","longitude":"-83"}',
        })

    def test_get_weather_uses_open_meteo_result(self):
        class ForecastResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "latitude": 42.28831,
                    "longitude": -83.700775,
                    "current": {"temperature_2m": 56.5},
                }

        class ForecastClient:
            async def get(self, url, params):
                self.url = url
                self.params = params
                return ForecastResponse()

        client = ForecastClient()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(client=client)))
        result = asyncio.run(handlers.getWeather(request, "42.292098", "-83.715880"))

        self.assertEqual(
            result,
            "Weather at lat: 42.28831, lon: -83.700775 is 56.5ºF",
        )
        self.assertEqual(client.url, handlers.OPEN_METEO_URL)
        self.assertEqual(client.params["temperature_unit"], "fahrenheit")


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
