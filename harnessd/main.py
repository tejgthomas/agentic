from httpx import AsyncClient, Timeout

from starlette.applications import Starlette
from starlette.routing import Route

import handlers
from runners import LlmRunners

routes = [
    Route("/", handlers.index, methods=["GET"]),
    Route("/llmprompt", handlers.llmprompt, methods=["POST"]),
    Route("/llmchat", handlers.llmchat, methods=["POST"]),
    Route("/llmtools", handlers.llmtools, methods=["POST"]),
    Route("/weather", handlers.weather, methods=["POST"]),
]

app = Starlette(routes=routes)
handlers.init_database()

app.state.runners = LlmRunners()
app.state.client = AsyncClient(
    timeout=Timeout(connect=5.0, read=None, write=None, pool=None),
    http2=True,
)
