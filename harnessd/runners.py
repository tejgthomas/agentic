from collections.abc import Iterator
import itertools
import math
import os
from pathlib import Path
import random
import sys

import msgspec
from msgspec import Struct


RUNNERS_CONFIG = os.environ.get(
    "RUNNERS_CONFIG",
    str(Path(__file__).resolve().parent.parent / "runners.toml"),
)


class LlmRunnerAPI(Struct):
    url: str
    key: str


class LlmRunner(Struct):
    api: LlmRunnerAPI
    model: str
    weight: float


class RawRunner(Struct):
    api: str
    model: str
    weight: float


class RawRunners(Struct):
    apis: dict[str, LlmRunnerAPI] = {}
    runners: list[RawRunner] = []


class LlmRunners:
    def __iter__(self) -> Iterator[LlmRunner]:
        scored = sorted(
            self.runners,
            key=lambda r: -math.log(random.random()) / (r.weight if r.weight > 0.0 else 1e-9),
        )

        if self.local:
            return itertools.chain(scored, (self.local,))

        return iter(scored)

    def __init__(self):
        print(f"Reading {RUNNERS_CONFIG}")

        try:
            toml_bytes = Path(RUNNERS_CONFIG).read_bytes()
        except FileNotFoundError:
            raise ValueError(f"Config file not found at {RUNNERS_CONFIG}")

        raw_runners = msgspec.toml.decode(toml_bytes, type=RawRunners)
        apis: dict[str, LlmRunnerAPI] = {}

        for runner, api in raw_runners.apis.items():
            key = os.environ.get(api.key) if api.key != "" else None

            if key:
                print(f"Runner {runner} ACTIVE", file=sys.stderr)
                apis[runner] = LlmRunnerAPI(url=api.url, key=key)
            elif runner == "local":
                if api.url:
                    print(f"Local runner {api.url} ACTIVE. API key {api.key}", file=sys.stderr)
                    apis[runner] = api
                else:
                    print("Local runner INACTIVE. No URL", file=sys.stderr)
            else:
                print(f"Runner {runner} INACTIVE: NO '{api.key}'", file=sys.stderr)

        if not apis:
            raise ValueError("CRITICAL: No API keys found and no local LLM configured.")

        self.runners: list[LlmRunner] = [
            LlmRunner(api=api, model=runner.model, weight=runner.weight)
            for runner in raw_runners.runners
            if (api := apis.get(runner.api)) is not None
        ]

        self.local: LlmRunner | None = None
        local = apis.get("local")
        if local is not None and local.url != "":
            self.local = LlmRunner(
                api=local,
                model="",
                weight=1.0,
            )
