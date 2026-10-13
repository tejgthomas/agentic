import asyncio
import sqlite3
import tempfile
import time
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

    def test_llmtools_request_decodes_tools_array(self):
        body = json.decode(
            b'{"appID":"app.one","model":"test-model","messages":[],'
            b'"tools":[{"type":"function","function":{"name":"get_location"}}]}',
            type=handlers.LlmToolsRequest,
        )

        self.assertEqual(json.decode(body.tools)[0]["function"]["name"], "get_location")

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

    def test_ticket_is_valid_only_before_expiration(self):
        with sqlite3.connect(handlers.DB_PATH) as db:
            db.execute(
                "INSERT INTO tickets(ticket, creator, expiration) VALUES (?, ?, ?)",
                ("valid", "Test User", int(time.time()) + 60),
            )
            db.execute(
                "INSERT INTO tickets(ticket, creator, expiration) VALUES (?, ?, ?)",
                ("expired", "Test User", int(time.time()) - 1),
            )

        self.assertTrue(handlers._valid_ticket("valid"))
        self.assertFalse(handlers._valid_ticket("expired"))
        self.assertFalse(handlers._valid_ticket("missing"))

    def test_google_token_requires_matching_audience_and_future_expiration(self):
        class TokenResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "aud": "client-id",
                    "exp": str(int(time.time()) + 60),
                    "name": "Test User",
                }

        class TokenClient:
            async def get(self, url, params):
                self.url = url
                self.params = params
                return TokenResponse()

        client = TokenClient()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(client=client)))
        profile = asyncio.run(handlers._verify_google_id_token(
            request, "client-id", "google-token"
        ))

        self.assertEqual(profile["name"], "Test User")
        self.assertEqual(client.url, handlers.GOOGLE_TOKEN_INFO_URL)
        self.assertEqual(client.params, {"id_token": "google-token"})

        with self.assertRaisesRegex(ValueError, "audience"):
            asyncio.run(handlers._verify_google_id_token(
                request, "different-client", "google-token"
            ))

    def test_addagent_issues_and_persists_ticket(self):
        class TokenResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "aud": "client-id",
                    "exp": str(int(time.time()) + 60),
                    "name": "Test User",
                }

        class TokenClient:
            async def get(self, url, params):
                return TokenResponse()

        class AddAgentRequest:
            client = SimpleNamespace(host="127.0.0.1")
            app = SimpleNamespace(state=SimpleNamespace(client=TokenClient()))

            async def body(self):
                return b'{"clientID":"client-id","idToken":"google-token"}'

        response = asyncio.run(handlers.addagent(AddAgentRequest()))
        payload = json.decode(response.body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["creator"], "Test User")
        self.assertEqual(payload["lifetime"], handlers.TICKET_LIFETIME)
        self.assertTrue(handlers._valid_ticket(payload["ticket"]))

    def test_addagent_rejects_invalid_google_token(self):
        class TokenResponse:
            def raise_for_status(self):
                raise ValueError("invalid token")

        class TokenClient:
            async def get(self, url, params):
                return TokenResponse()

        class AddAgentRequest:
            client = SimpleNamespace(host="127.0.0.1")
            app = SimpleNamespace(state=SimpleNamespace(client=TokenClient()))

            async def body(self):
                return b'{"clientID":"client-id","idToken":"invalid"}'

        response = asyncio.run(handlers.addagent(AddAgentRequest()))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.body, b"Unauthorized")
        with sqlite3.connect(handlers.DB_PATH) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM tickets").fetchone()[0], 0)

    def test_authorized_resident_weather_tool_runs_and_completes_turn(self):
        with sqlite3.connect(handlers.DB_PATH) as db:
            db.execute(
                "INSERT INTO tickets(ticket, creator, expiration) VALUES (?, ?, ?)",
                ("valid-ticket", "Test User", int(time.time()) + 60),
            )
        body = handlers.LlmToolsRequest(
            appID="app.one",
            model="test-model",
            messages=Raw(json.encode([handlers.Message(role="user", content="Weather?")])),
        )
        turn = handlers._prepare_tools_turn(body)
        context = handlers._tools_context("app.one", turn)
        routed = handlers.OpenAIRequest(
            model="test-model",
            messages=Raw(json.encode(context)),
            stream=True,
        )
        arguments = json.encode({
            "ticket": "valid-ticket",
            "latitude": "42.28",
            "longitude": "-83.74",
        }).decode()
        tool_event = json.encode({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "weather-call",
                        "function": {
                            "name": "get_weather_auth",
                            "arguments": arguments,
                        },
                    }],
                },
            }],
        }).decode()
        initial = Response(
            200,
            content=_ChunkedStream([f"data: {tool_event}\n\ndata: [DONE]\n\n".encode()]),
            request=Request("POST", "https://runner.test/v1/chat/completions"),
        )

        class ForecastResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "latitude": 42.28,
                    "longitude": -83.74,
                    "current": {"temperature_2m": 60.0},
                }

        class ForecastClient:
            called = False

            async def get(self, url, params):
                self.called = True
                return ForecastResponse()

        forecast_client = ForecastClient()
        request = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            app=SimpleNamespace(state=SimpleNamespace(client=forecast_client)),
        )
        final_event = (
            'data: {"choices":[{"delta":{"content":"It is 60F."}}]}\n\n'
            'data: [DONE]\n\n'
        ).encode()
        original_route = handlers._route_prompt

        async def route_final(_request, routed_request):
            messages = json.decode(routed_request.messages, type=list[handlers.Message])
            self.assertEqual(messages[-1].role, "tool")
            self.assertIn("60.0ºF", messages[-1].content)
            return Response(
                200,
                content=_ChunkedStream([final_event]),
                request=Request("POST", "https://runner.test/v1/chat/completions"),
            )

        handlers._route_prompt = route_final
        try:
            streamed = asyncio.run(_collect(
                handlers._stream_tools(request, initial, routed, turn)
            ))
        finally:
            handlers._route_prompt = original_route

        self.assertTrue(forecast_client.called)
        self.assertTrue(streamed.endswith(final_event))
        self.assertNotIn(b"get_weather_auth", streamed)
        with sqlite3.connect(handlers.DB_PATH) as db:
            completion, result = db.execute(
                """SELECT turns.completion, calls.result FROM turns
                   JOIN calls USING(turnID) WHERE turns.turnID = ?""",
                (turn,),
            ).fetchone()
        self.assertEqual(completion, "It is 60F.")
        self.assertIn("60.0ºF", result)


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
