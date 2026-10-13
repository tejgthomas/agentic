# llmHITL

iOS SwiftUI agent and Python Starlette `harnessd` backend for the UM EECS
Agentic llmHITL tutorial. This branch builds from the completed `llmTools`
tag; the `llmChat`, `llmPlay`, and `llmTools` milestone tags remain unchanged.

## Personal configuration required

Before running the iOS app, create an iOS OAuth client for the bundle ID
`edu.umich.tejg.agent`. In both Debug and Release settings for the Agent target,
replace:

- `GOOGLE_CLIENT_ID = YOUR_CLIENT_ID` with the `CLIENT_ID` from Google's
  downloaded credentials plist.
- `GOOGLE_REVERSED_CLIENT_ID = YOUR_REVERSED_CLIENT_ID` with its
  `REVERSED_CLIENT_ID`.

The project already includes the GoogleSignIn and GoogleSignInSwift package
products, the generated Info.plist entries, and the Face ID usage description.
The OAuth client values are account-specific and are intentionally not invented
or committed here.

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
