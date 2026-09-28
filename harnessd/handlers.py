from http import HTTPStatus
import codecs
import logging
import sqlite3
from pathlib import Path

from httpx import RequestError, Response
from msgspec import Raw, Struct, json, structs
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import PlainTextResponse, StreamingResponse


class Message(Struct, omit_defaults=True):
    role: str
    content: str | None


class OpenAIRequest(Struct, omit_defaults=True):
    model: str
    messages: Raw
    stream: bool = False


class LlmChatRequest(Struct, omit_defaults=True):
    appID: str
    model: str
    messages: Raw
    stream: bool = True


class Delta(Struct, omit_defaults=True):
    content: str | None = None
    reasoning: str | None = None
    reasoning_content: str | None = None


class Choice(Struct, omit_defaults=True):
    delta: Delta | None = None
    finish_reason: str | None = None


class OpenAIResponse(Struct, omit_defaults=True):
    choices: list[Choice]


DB_PATH = Path(__file__).with_name("harnessd.db")

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
        return _log_client_err(
            client_ip,
            HTTPStatus.SERVICE_UNAVAILABLE,
            "All available LLM providers are rate limited or offline.",
        )

    return StreamingResponse(
        response.aiter_raw(),
        headers={"Content-Type": "text/event-stream"},
        background=BackgroundTask(response.aclose),
    )


async def llmchat(request: Request):
    client_ip = request.client.host if request.client else "Unknown"
    try:
        openai_request = json.decode(await request.body(), type=LlmChatRequest)
    except Exception:
        return _log_client_err(client_ip, HTTPStatus.BAD_REQUEST, "Invalid JSON body.")

    try:
        turn_id = _insert_prompt(openai_request)
        messages = _conversation_context(openai_request.appID)
    except Exception as e:
        logger.exception("SQLite error while preparing llmchat turn.")
        return StreamingResponse(
            _sse_error(f"SQLite error while preparing llmchat turn: {e}"),
            headers={"Content-Type": "text/event-stream"},
            status_code=HTTPStatus.OK,
        )

    routed_request = OpenAIRequest(
        model=openai_request.model,
        messages=Raw(json.encode(messages)),
        stream=openai_request.stream,
    )
    response = await _route_prompt(request, routed_request)
    if response is None:
        return _log_client_err(
            client_ip,
            HTTPStatus.SERVICE_UNAVAILABLE,
            "All available LLM providers are rate limited or offline.",
        )

    return StreamingResponse(
        _stream_and_persist(response, turn_id),
        headers={"Content-Type": "text/event-stream"},
        background=BackgroundTask(response.aclose),
    )


async def llmclear(request: Request):
    client_ip = request.client.host if request.client else "Unknown"
    try:
        openai_request = json.decode(await request.body(), type=LlmChatRequest)
    except Exception:
        return _log_client_err(client_ip, HTTPStatus.BAD_REQUEST, "Invalid JSON body.")

    try:
        _clear_context(openai_request.appID)
    except Exception:
        logger.exception("SQLite error while clearing llmchat context.")
        return _log_client_err(
            client_ip,
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "Unable to clear conversation context.",
        )

    return PlainTextResponse("Conversation context cleared.", status_code=HTTPStatus.OK)


async def _route_prompt(request: Request, openai_request: OpenAIRequest) -> Response | None:
    client_ip = request.client.host if request.client else "Unknown"

    request_body = structs.replace(openai_request)
    client = request.app.state.client
    runners = request.app.state.runners

    for runner in runners:
        request_body.model = runner.model or openai_request.model

        headers = {"Content-Type": "application/json"}
        if runner.api.key:
            headers["Authorization"] = f"Bearer {runner.api.key}"

        try:
            response = await client.send(
                client.build_request(
                    method=request.method,
                    url=f"{runner.api.url}/v1/chat/completions",
                    headers=headers,
                    content=json.encode(request_body),
                ),
                stream=True,
            )

            if response.status_code != HTTPStatus.OK:
                _log_info(
                    client_ip,
                    runner.api.url,
                    runner.model,
                    response.status_code,
                    "Server error. Trying another one.",
                )
                await response.aclose()
                continue

            _log_ok(client_ip, runner.api.url, runner.model)
            return response

        except RequestError as e:
            _log_info(
                client_ip,
                runner.api.url,
                runner.model,
                HTTPStatus.PROCESSING,
                f"Connection error: {e}. Trying another one.",
            )
            continue

    return None


def init_database():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(
            """
            PRAGMA page_size = 16384;
            PRAGMA journal_mode = WAL;
            PRAGMA auto_vacuum = INCREMENTAL;
            CREATE TABLE IF NOT EXISTS turns (
                turnID INTEGER PRIMARY KEY,
                appID TEXT NOT NULL,
                prompt BLOB NOT NULL,
                reasoning TEXT,
                completion TEXT,
                completed INTEGER,
                prompt_ts INTEGER NOT NULL DEFAULT (unixepoch()),
                completion_ts INTEGER
            );
            CREATE TRIGGER IF NOT EXISTS completion_ts_trg
            AFTER UPDATE OF completion ON turns
            WHEN NEW.completion IS NOT NULL AND OLD.completion IS NULL
            BEGIN
                UPDATE turns
                SET completion_ts = unixepoch()
                WHERE turnID = NEW.turnID;
            END;
            CREATE INDEX IF NOT EXISTS turns_idx ON turns(appID, turnID);
            """
        )


def _connect_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode = WAL")
    return db


def _insert_prompt(openai_request: LlmChatRequest) -> int:
    messages = json.decode(openai_request.messages, type=list[Message])
    if not messages or not any(message.content for message in messages):
        raise ValueError("messages must include content.")

    with _connect_db() as db:
        cursor = db.execute(
            "INSERT INTO turns(appID, prompt, completed) VALUES (?, ?, 0)",
            (openai_request.appID, json.encode(messages)),
        )
        return int(cursor.lastrowid)


def _conversation_context(app_id: str) -> list[Message]:
    messages: list[Message] = []
    with _connect_db() as db:
        rows = db.execute(
            """
            SELECT typeof(prompt), prompt, completion
            FROM turns
            WHERE appID = ?
            ORDER BY turnID
            """,
            (app_id,),
        )

        for storage_type, prompt, completion in rows:
            if storage_type == "blob":
                messages.extend(json.decode(prompt, type=list[Message]))
            else:
                messages.append(Message(role="user", content=prompt))
            if completion:
                messages.append(Message(role="assistant", content=completion))

    return messages


def _clear_context(app_id: str):
    with _connect_db() as db:
        db.execute("DELETE FROM turns WHERE appID = ?", (app_id,))


async def _stream_and_persist(response: Response, turn_id: int):
    completion: list[str] = []
    reasoning: list[str] = []
    pending = ""
    decoder = codecs.getincrementaldecoder("utf-8")()

    try:
        async for chunk in response.aiter_raw():
            yield chunk
            pending += decoder.decode(chunk)
            pending = _accumulate_sse_lines(pending, completion, reasoning)

        pending += decoder.decode(b"", final=True)
        _accumulate_sse_lines(f"{pending}\n", completion, reasoning)
    except Exception as e:
        logger.exception("LLM stream failed during llmchat turn.")
        async for event in _sse_error(f"LLM stream failed: {e}"):
            yield event
        return

    try:
        _update_completion(
            turn_id,
            "".join(completion),
            "".join(reasoning) or None,
        )
    except Exception as e:
        logger.exception("SQLite error while saving llmchat completion.")
        async for event in _sse_error(f"SQLite error while saving llmchat completion: {e}"):
            yield event


def _accumulate_sse_lines(pending: str, completion: list[str], reasoning: list[str]) -> str:
    while "\n" in pending:
        line, pending = pending.split("\n", 1)
        line = line.rstrip("\r")
        if not line.startswith("data:"):
            continue

        data = line.removeprefix("data:").lstrip()
        if not data or data == "[DONE]":
            continue

        try:
            chunk = json.decode(data.encode(), type=OpenAIResponse)
        except Exception:
            continue

        if not chunk.choices or chunk.choices[0].delta is None:
            continue

        delta = chunk.choices[0].delta
        if delta.content:
            completion.append(delta.content)
        if delta.reasoning:
            reasoning.append(delta.reasoning)
        if delta.reasoning_content:
            reasoning.append(delta.reasoning_content)

    return pending


def _update_completion(turn_id: int, completion: str, reasoning: str | None):
    with _connect_db() as db:
        db.execute(
            """
            UPDATE turns
            SET completion = ?, reasoning = ?, completed = 1
            WHERE turnID = ?
            """,
            (completion, reasoning, turn_id),
        )


async def _sse_error(message: str):
    yield f"event: error\ndata: {message}\n\n".encode()
