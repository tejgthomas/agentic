# Project 1: Where in the World?

iOS SwiftUI Guess the City and Guess the Landmark games with a Python Starlette `harnessd` backend. The project builds directly on the tagged `llmChat` tutorial baseline.

## Project Layout

```text
.
|-- AGENTS.md
|-- README.md
|-- Agent
|   |-- Agent.xcodeproj
|   |-- Agent
|-- harnessd
```

## Endpoints

* `POST /llmchat` streams completions and persists context by appID.
* `POST /llmclear` reuses the same request shape and clears context by appID.
* The submitted client uses `edu.umich.tejg.agent` and the project backend at `https://34.56.51.226`.

## Team

Tejvir Thomas (`tejgthomas19`) completed the frontend, backend, testing, deployment, and design document individually.

GitHub repo: <https://github.com/tejgthomas/agentic.git>

## Honor Code Pledge

"I [ HAVE ] received aid from an LLM or automated coding
assistant on this submitted work. If I received aid, the specific
tool used was (specify model and version): [OpenAI Codex, GPT-5].
Regardless of assistance, I fully understand and can defend all code
and design choices within this submission, and I have not concealed
any violations of the Honor Code."

Signed: Tejvir Thomas, 00619123  Date: September 28, 2026
