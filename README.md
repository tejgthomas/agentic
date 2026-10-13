# llmHITL

iOS SwiftUI agent and Python Starlette `harnessd` backend for the UM EECS
Agentic llmHITL tutorial. This branch builds from the completed `llmTools`
tag; the `llmChat`, `llmPlay`, and `llmTools` milestone tags remain unchanged.

## Personal configuration required

The Agent target is configured with its Google iOS OAuth client for bundle ID
`edu.umich.tejg.agent`. The project includes the GoogleSignIn and
GoogleSignInSwift package products, generated Info.plist entries, reversed-client
URL scheme, and Face ID usage description.

The backend also needs at least one configured runner API key or local runner,
as described in `harnessd/README.md`.

## HITL behavior

- `POST /addagent` validates a Google ID token and returns a ten-minute ticket.
- `get_auth` restores or performs Google Sign-In, obtains a ticket, and stores it
  in a biometric-protected Keychain item.
- `get_loc_auth` exposes device location only for the current ticket.
- `get_weather_auth` validates that ticket against the backend database before
  calling Open-Meteo.

The implementation checklist derived from the supplied tutorial is preserved in
[`docs/llmHITL-spec.md`](docs/llmHITL-spec.md).

## Honor Code Pledge

"I [ HAVE ] received aid from an LLM or automated coding assistant on this
submitted work. If I received aid, the specific tool used was (specify model and
version): [OpenAI Codex, GPT-5]. Regardless of assistance, I fully understand
and can defend all code and design choices within this submission, and I have
not concealed any violations of the Honor Code."

Signed: Tejvir Thomas, 00619123
