from http import HTTPStatus
import logging
import sqlite3
from pathlib import Path

from httpx import RequestError, Response
from msgspec import Raw, Struct, json, structs
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import PlainTextResponse, StreamingResponse


class OpenAIFunction(Struct, omit_defaults=True):
    name: str | None = None
    arguments: str | None = None


class OpenAIToolCall(Struct):
    id: str
    function: OpenAIFunction
    type: str = "function"


class Message(Struct, omit_defaults=True):
    role: str
    content: str | None = None
    tool_calls: list[OpenAIToolCall] | None = None
    tool_call_id: str | None = None


class OpenAIRequest(Struct, omit_defaults=True):
    model: str
    messages: Raw
    stream: bool = False
    tools: Raw = Raw(b"null")


class LlmChatRequest(Struct, omit_defaults=True):
    appID: str
    model: str
    messages: Raw
    stream: bool = True


class LlmToolsRequest(Struct, omit_defaults=True):
    appID: str
    model: str
    messages: Raw
    turnID: int | None = None
    tools: Raw = Raw(b"null")
    stream: bool = True


class WeatherRequest(Struct):
    lat: str
    lon: str


class FunctionDelta(Struct, omit_defaults=True):
    name: str | None = None
    arguments: str | None = None


class ToolCallDelta(Struct, omit_defaults=True):
    index: int
    id: str | None = None
    function: FunctionDelta | None = None


class Delta(Struct, omit_defaults=True):
    content: str | None = None
    reasoning: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[ToolCallDelta] | None = None


class Choice(Struct, omit_defaults=True):
    delta: Delta | None = None
    finish_reason: str | None = None


class OpenAIResponse(Struct, omit_defaults=True):
    choices: list[Choice] = []


DB_PATH = Path(__file__).with_name("harnessd.db")
WEATHER_SCHEMA_PATH = Path(__file__).with_name("tools") / "get_weather.json"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

logger = logging.getLogger("runner")
logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)


def _log_ok(client_ip: str, runner: str, model: str):
    logger.info(f"{client_ip} | {runner}:{model}")


def _log_info(client_ip: str, runner: str, model: str, errcode: int, msg: str):
    logger.info(f"{errcode} | {client_ip} | {runner}:{model} {msg} |")


def _log_client_err(client_ip: str, errcode: HTTPStatus, errmsg: str) -> PlainTextResponse:
    logger.warning(f"{errcode.value} | {client_ip} |")
    return PlainTextResponse(status_code=errcode, content=errmsg)


async def index(request: Request):
    return PlainTextResponse("UM EECS Agentic harnessd", status_code=HTTPStatus.OK)


async def llmprompt(request: Request):
    client_ip = request.client.host if request.client else "Unknown"
    try:
        openai_request = json.decode(await request.body(), type=OpenAIRequest)
    except Exception:
        return _log_client_err(client_ip, HTTPStatus.BAD_REQUEST, "Invalid JSON body.")
    response = await _route_prompt(request, openai_request)
    if response is None:
        return _log_client_err(client_ip, HTTPStatus.SERVICE_UNAVAILABLE,
                               "All available LLM providers are rate limited or offline.")
    return StreamingResponse(response.aiter_raw(),
                             headers={"Content-Type": "text/event-stream"},
                             background=BackgroundTask(response.aclose))


async def llmchat(request: Request):
    client_ip = request.client.host if request.client else "Unknown"
    try:
        openai_request = json.decode(await request.body(), type=LlmChatRequest)
    except Exception:
        return _log_client_err(client_ip, HTTPStatus.BAD_REQUEST, "Invalid JSON body.")
    try:
        turn_id = _insert_prompt(openai_request)
        messages = _conversation_context(openai_request.appID)
    except Exception as error:
        logger.exception("SQLite error while preparing llmchat turn.")
        return StreamingResponse(_sse_error(f"SQLite error while preparing llmchat turn: {error}"),
                                 headers={"Content-Type": "text/event-stream"})
    routed = OpenAIRequest(model=openai_request.model,
                           messages=Raw(json.encode(messages)),
                           stream=openai_request.stream)
    response = await _route_prompt(request, routed)
    if response is None:
        return _log_client_err(client_ip, HTTPStatus.SERVICE_UNAVAILABLE,
                               "All available LLM providers are rate limited or offline.")
    return StreamingResponse(_stream_chat(response, turn_id),
                             headers={"Content-Type": "text/event-stream"},
                             background=BackgroundTask(response.aclose))


async def weather(request: Request):
    client_ip = request.client.host if request.client else "Unknown"
    try:
        body = json.decode(await request.body(), type=WeatherRequest)
        result = await getWeather(request, body.lat, body.lon)
    except Exception as error:
        return _log_client_err(client_ip, HTTPStatus.BAD_REQUEST, str(error))
    return PlainTextResponse(result, status_code=HTTPStatus.OK)


async def llmtools(request: Request):
    client_ip = request.client.host if request.client else "Unknown"
    try:
        body = json.decode(await request.body(), type=LlmToolsRequest)
        turn_id = _prepare_tools_turn(body)
        messages = _tools_context(body.appID, turn_id)
        schemas = _tool_schemas(body.appID)
    except Exception as error:
        logger.exception("Error while preparing llmtools turn.")
        return StreamingResponse(_sse_error(f"Error while preparing llmtools turn: {error}"),
                                 headers={"Content-Type": "text/event-stream"})
    routed = OpenAIRequest(model=body.model, messages=Raw(json.encode(messages)),
                           tools=Raw(json.encode(schemas)), stream=body.stream)
    response = await _route_prompt(request, routed)
    if response is None:
        return _log_client_err(client_ip, HTTPStatus.SERVICE_UNAVAILABLE,
                               "All available LLM providers are rate limited or offline.")
    return StreamingResponse(_stream_tools(request, response, routed, turn_id),
                             headers={"Content-Type": "text/event-stream"})


async def getWeather(request: Request, lat: str, lon: str) -> str:
    response = await request.app.state.client.get(
        OPEN_METEO_URL,
        params={"latitude": lat, "longitude": lon, "current": "temperature_2m",
                "temperature_unit": "fahrenheit"},
    )
    response.raise_for_status()
    forecast = response.json()
    return (f"Weather at lat: {forecast['latitude']}, lon: {forecast['longitude']} "
            f"is {forecast['current']['temperature_2m']}ºF")


async def _route_prompt(request: Request, openai_request: OpenAIRequest) -> Response | None:
    client_ip = request.client.host if request.client else "Unknown"
    request_body = structs.replace(openai_request)
    for runner in request.app.state.runners:
        request_body.model = runner.model or openai_request.model
        headers = {"Content-Type": "application/json"}
        if runner.api.key:
            headers["Authorization"] = f"Bearer {runner.api.key}"
        try:
            response = await request.app.state.client.send(
                request.app.state.client.build_request(
                    method="POST", url=f"{runner.api.url}/v1/chat/completions",
                    headers=headers, content=json.encode(request_body)), stream=True)
            if response.status_code != HTTPStatus.OK:
                _log_info(client_ip, runner.api.url, runner.model, response.status_code,
                          "Server error. Trying another one.")
                await response.aclose()
                continue
            _log_ok(client_ip, runner.api.url, runner.model)
            return response
        except RequestError as error:
            _log_info(client_ip, runner.api.url, runner.model, HTTPStatus.PROCESSING,
                      f"Connection error: {error}. Trying another one.")
    return None


def init_database():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
            PRAGMA page_size = 16384;
            PRAGMA journal_mode = WAL;
            PRAGMA auto_vacuum = INCREMENTAL;
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS turns (
                turnID INTEGER PRIMARY KEY, appID TEXT NOT NULL, prompt BLOB NOT NULL,
                reasoning TEXT, completion TEXT, completed INTEGER,
                prompt_ts INTEGER NOT NULL DEFAULT (unixepoch()), completion_ts INTEGER
            );
            CREATE TRIGGER IF NOT EXISTS completion_ts_trg
            AFTER UPDATE OF completion ON turns
            WHEN NEW.completion IS NOT NULL AND OLD.completion IS NULL
            BEGIN
                UPDATE turns SET completion_ts = unixepoch() WHERE turnID = NEW.turnID;
            END;
            CREATE INDEX IF NOT EXISTS turns_idx ON turns(appID, turnID);
            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY, idx INTEGER NOT NULL, turnID INTEGER NOT NULL,
                name TEXT NOT NULL, arguments TEXT NOT NULL, result TEXT,
                call_ts INTEGER NOT NULL DEFAULT (unixepoch()), result_ts INTEGER,
                FOREIGN KEY(turnID) REFERENCES turns(turnID)
            );
            CREATE TRIGGER IF NOT EXISTS result_ts_trg
            AFTER UPDATE OF result ON calls
            WHEN NEW.result IS NOT NULL AND OLD.result IS NULL
            BEGIN
                UPDATE calls SET result_ts = unixepoch() WHERE id = NEW.id;
            END;
            CREATE INDEX IF NOT EXISTS calls_idx ON calls(turnID, idx);
            CREATE TABLE IF NOT EXISTS tools (
                appID TEXT PRIMARY KEY, schemas BLOB,
                timestamp INTEGER NOT NULL DEFAULT (unixepoch())
            );
        """)


def _connect_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _insert_prompt(openai_request: LlmChatRequest) -> int:
    messages = json.decode(openai_request.messages, type=list[Message])
    with _connect_db() as db:
        cursor = db.execute("INSERT INTO turns(appID, prompt, completed) VALUES (?, ?, 0)",
                            (openai_request.appID, _latest_user_prompt(messages)))
        return int(cursor.lastrowid)


def _latest_user_prompt(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.content:
            return message.content
    raise ValueError("messages must include a user message with content.")


def _conversation_context(app_id: str) -> list[Message]:
    messages: list[Message] = []
    with _connect_db() as db:
        rows = db.execute("SELECT prompt, completion FROM turns WHERE appID = ? ORDER BY turnID",
                          (app_id,))
        for prompt, completion in rows:
            messages.append(Message(role="user", content=prompt))
            if completion:
                messages.append(Message(role="assistant", content=completion))
    return messages


def _prepare_tools_turn(body: LlmToolsRequest) -> int:
    messages = json.decode(body.messages, type=list[Message])
    with _connect_db() as db:
        if body.turnID is None:
            if not messages or not any(message.content for message in messages):
                raise ValueError("messages must include content.")
            cursor = db.execute("INSERT INTO turns(appID, prompt, completed) VALUES (?, ?, 0)",
                                (body.appID, json.encode(messages)))
            turn_id = int(cursor.lastrowid)
            if bytes(body.tools) != b"null":
                db.execute("""INSERT INTO tools(appID, schemas) VALUES (?, ?)
                           ON CONFLICT(appID) DO UPDATE SET schemas = excluded.schemas,
                           timestamp = unixepoch()""", (body.appID, bytes(body.tools)))
            return turn_id
        owner = db.execute("SELECT appID FROM turns WHERE turnID = ?", (body.turnID,)).fetchone()
        if owner is None or owner[0] != body.appID:
            raise ValueError("turnID does not belong to appID.")
        for message in messages:
            if message.role != "tool" or not message.tool_call_id:
                raise ValueError("follow-up messages must be tool results.")
            updated = db.execute("UPDATE calls SET result = ? WHERE id = ? AND turnID = ?",
                                 (message.content, message.tool_call_id, body.turnID))
            if updated.rowcount != 1:
                raise ValueError(f"unknown tool_call_id {message.tool_call_id}.")
        return body.turnID


def _tool_schemas(app_id: str) -> list[object]:
    with _connect_db() as db:
        row = db.execute("SELECT schemas FROM tools WHERE appID = ?", (app_id,)).fetchone()
    client_schemas = json.decode(row[0]) if row and row[0] else []
    return [*client_schemas, json.decode(WEATHER_SCHEMA_PATH.read_bytes())]


def _tools_context(app_id: str, through_turn_id: int) -> list[Message]:
    context: list[Message] = []
    with _connect_db() as db:
        turns = db.execute("""SELECT turnID, typeof(prompt), prompt, completion FROM turns
                           WHERE appID = ? AND turnID <= ? ORDER BY turnID""",
                           (app_id, through_turn_id)).fetchall()
        for turn_id, storage_type, prompt, completion in turns:
            if storage_type == "blob":
                context.extend(json.decode(prompt, type=list[Message]))
            else:
                context.append(Message(role="user", content=prompt))
            for calls in _call_groups_for_turn(db, turn_id):
                context.append(Message(role="assistant", tool_calls=[call for call, _ in calls]))
                context.extend(Message(role="tool", content=result, tool_call_id=call.id)
                               for call, result in calls if result is not None)
            if completion:
                context.append(Message(role="assistant", content=completion))
    return context


def _call_groups_for_turn(db: sqlite3.Connection, turn_id: int):
    rows = db.execute("""SELECT idx, id, name, arguments, result FROM calls
                      WHERE turnID = ? ORDER BY call_ts, rowid""", (turn_id,))
    groups = []
    for index, call_id, name, arguments, result in rows:
        if index == 0:
            groups.append([])
        if not groups:
            raise ValueError("tool call group does not begin at index 0.")
        groups[-1].append((OpenAIToolCall(
            id=call_id, function=OpenAIFunction(name=name, arguments=arguments)), result))
    return groups


def _record_calls(turn_id: int, calls: list[OpenAIToolCall]):
    with _connect_db() as db:
        db.executemany("INSERT INTO calls(id, idx, turnID, name, arguments) VALUES (?, ?, ?, ?, ?)",
                       [(call.id, index, turn_id, call.function.name,
                         call.function.arguments or "") for index, call in enumerate(calls)])


def _record_result(call_id: str, result: str):
    with _connect_db() as db:
        db.execute("UPDATE calls SET result = ? WHERE id = ?", (result, call_id))


async def _stream_chat(response: Response, turn_id: int):
    completion: list[str] = []
    reasoning: list[str] = []
    try:
        async for line in response.aiter_lines():
            yield f"{line}\n".encode()
            _accumulate_chunk(_decode_data_line(line), completion, reasoning)
    except Exception as error:
        logger.exception("LLM stream failed during llmchat turn.")
        async for event in _sse_error(f"LLM stream failed: {error}"):
            yield event
        return
    _update_completion(turn_id, "".join(completion), "".join(reasoning) or None)


async def _stream_tools(request: Request, response: Response,
                        routed: OpenAIRequest, turn_id: int):
    current_response = response
    while True:
        completion: list[str] = []
        reasoning: list[str] = []
        call_parts: dict[int, dict[str, str]] = {}
        try:
            async for line in current_response.aiter_lines():
                chunk = _decode_data_line(line)
                if not _accumulate_tool_deltas(chunk, call_parts):
                    yield f"{line}\n".encode()
                    _accumulate_chunk(chunk, completion, reasoning)
        except Exception as error:
            logger.exception("LLM stream failed during llmtools turn.")
            async for event in _sse_error(f"LLM stream failed: {error}"):
                yield event
            return
        finally:
            await current_response.aclose()
        calls = [OpenAIToolCall(id=part["id"], function=OpenAIFunction(
            name=part.get("name"), arguments=part.get("arguments", "")))
                 for _, part in sorted(call_parts.items())]
        if not calls:
            _update_completion(turn_id, "".join(completion), "".join(reasoning) or None)
            return
        _record_calls(turn_id, calls)
        remote_calls: list[OpenAIToolCall] = []
        resident_results: list[Message] = []
        for call in calls:
            if call.function.name == "get_weather":
                try:
                    arguments = json.decode((call.function.arguments or "{}").encode())
                    result = await getWeather(request, str(arguments["latitude"]),
                                              str(arguments["longitude"]))
                except Exception as error:
                    result = f"get_weather failed: {error}"
                _record_result(call.id, result)
                resident_results.append(Message(role="tool", content=result,
                                                tool_call_id=call.id))
            else:
                remote_calls.append(call)
        if remote_calls:
            payload = json.encode({"turnID": turn_id, "calls": remote_calls}).decode()
            yield f"event: tool_calls\ndata: {payload}\n\n".encode()
            return
        context = json.decode(routed.messages, type=list[Message])
        context.append(Message(role="assistant", tool_calls=calls))
        context.extend(resident_results)
        routed.messages = Raw(json.encode(context))
        current_response = await _route_prompt(request, routed)
        if current_response is None:
            async for event in _sse_error("All available LLM providers are unavailable."):
                yield event
            return


def _decode_data_line(line: str) -> OpenAIResponse | None:
    if not line.startswith("data:"):
        return None
    data = line.removeprefix("data:").lstrip()
    if not data or data == "[DONE]":
        return None
    try:
        return json.decode(data.encode(), type=OpenAIResponse)
    except Exception:
        return None


def _accumulate_tool_deltas(chunk: OpenAIResponse | None,
                            call_parts: dict[int, dict[str, str]]) -> bool:
    if chunk is None:
        return False
    found = False
    for choice in chunk.choices:
        if choice.delta is None or not choice.delta.tool_calls:
            continue
        found = True
        for delta in choice.delta.tool_calls:
            part = call_parts.setdefault(delta.index, {})
            if delta.id:
                part["id"] = delta.id
            if delta.function:
                if delta.function.name:
                    part["name"] = part.get("name", "") + delta.function.name
                if delta.function.arguments:
                    part["arguments"] = part.get("arguments", "") + delta.function.arguments
    return found


def _accumulate_chunk(chunk: OpenAIResponse | None,
                      completion: list[str], reasoning: list[str]):
    if chunk is None:
        return
    for choice in chunk.choices:
        if choice.delta is None:
            continue
        if choice.delta.content:
            completion.append(choice.delta.content)
        if choice.delta.reasoning:
            reasoning.append(choice.delta.reasoning)
        if choice.delta.reasoning_content:
            reasoning.append(choice.delta.reasoning_content)


def _update_completion(turn_id: int, completion: str, reasoning: str | None):
    with _connect_db() as db:
        db.execute("""UPDATE turns SET completion = ?, reasoning = ?, completed = 1
                   WHERE turnID = ?""", (completion, reasoning, turn_id))


async def _sse_error(message: str):
    yield f"event: error\ndata: {message}\n\n".encode()
