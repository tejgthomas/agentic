# llmHITL specification checklist

This checklist preserves the requirements supplied for this tutorial. The full
tutorial text remains the source of truth.

## Repository isolation

- Branch `llmHITL` from the completed `llmTools` tag.
- Do not modify the `llmChat`, `llmPlay`, or `llmTools` milestone tags.
- Preserve inherited chat, streaming, context, and tool-call behavior except for
  the explicit authorization substitutions below.

## SwiftUI front end

- Add GoogleSignIn and GoogleSignInSwift through Swift Package Manager.
- Configure the Google client ID and reversed-client-ID URL scheme.
- Restore an existing Google sign-in before presenting the sign-in button.
- Exchange the Google ID token with `POST /addagent`.
- Represent ticket, creator, and expiration in a singleton.
- Load a saved ticket on launch and save refreshed tickets.
- Protect Keychain access with user-presence authentication and support the
  simulator authentication path.
- Add `get_auth` and `get_loc_auth`; remove `get_location` from advertised tools.
- Trigger sign-in from the network-initiated tool call and resume it after the
  sign-in sheet closes.
- Show advisory and error alerts and configure the Face ID usage description.

## Python back end

- Add `POST /addagent` accepting `{ clientID, idToken }`.
- Validate the Google ID token and its audience; return 401 when invalid.
- Generate a limited-lifetime random ticket and store its creator and expiration.
- Create the `tickets` table, expiration index, and timestamp view idempotently.
- Advertise `get_weather_auth` instead of `get_weather`.
- Require a live stored ticket before the resident weather tool calls Open-Meteo.
- Return an authorization failure that directs the LLM to obtain a fresh ticket.

## Manual completion and acceptance

- Supply personal Google OAuth client values for bundle ID
  `edu.umich.tejg.agent`.
- Run Google Sign-In on a simulator or device with the backend reachable.
- Verify valid and invalid `/addagent` requests using a real ID token.
- Verify biometric save, app relaunch/restore, expiration, and cancellation.
- Verify the complete prompt: “What is the weather at my location?”
- Commit and push both halves, then create and push the `llmHITL` milestone tag
  only after end-to-end verification.
