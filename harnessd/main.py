from httpx import AsyncClient, Timeout

from starlette.applications import Starlette
from starlette.routing import Route

import handlers
from runners import LlmRunners

routes = [
    Route("/", handlers.index, methods=["GET"]),
    Route("/llmprompt", handlers.llmprompt, methods=["POST"]),
]

app = Starlette(routes=routes)

app.state.runners = LlmRunners()
app.state.client = AsyncClient(
    timeout=Timeout(connect=5.0, read=None, write=None, pool=None),
    http2=True,
)
