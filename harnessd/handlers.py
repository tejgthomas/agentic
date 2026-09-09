from http import HTTPStatus
import logging

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
