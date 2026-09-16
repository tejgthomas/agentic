# llmChat

iOS SwiftUI mobile agent and Python Starlette `harnessd` backend for the UM EECS Agentic llmChat tutorial. This builds on the previous llmPrompt submission in the same GitHub repo.

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

## What Still Needs Your Personal Values

Update these before final submission:

* `Agent/Agent/Rein.swift` `harness` value to your own HTTPS backend after deployment. The app currently points at `https://mada.eecs.umich.edu` for frontend testing.
* `runners.toml` and your server environment variables with at least one real LLM runner API key, or a working local runner URL.
* `harnessd/harnessd.py` certificate paths if your deployed Ubuntu username/path differs from `/home/ubuntu/agentic`.
* The front end sends `edu.umich.tejg.agent` as its `appID`, matching the current iOS bundle identifier.

GitHub repo: <https://github.com/tejgthomas/llmPrompt.git>

## Honor Code Pledge

"I [ HAVE ] received aid from an LLM or automated coding
assistant on this submitted work. If I received aid, the specific
tool used was (specify model and version): [OpenAI Codex, GPT-5].
Regardless of assistance, I fully understand and can defend all code
and design choices within this submission, and I have not concealed
any violations of the Honor Code."

Signed: Tejvir Thomas, 00619123  Date: September 9, 2026
