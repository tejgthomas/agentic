# harnessd

Python Starlette/Granian implementation of the llmPrompt and llmChat backend.

## Deploy Notes

1. Clone this repository as `~/agentic`, then create the backend virtual environment and install its dependencies:

```sh
cd ~/agentic/harnessd
python3 -m venv .venv
.venv/bin/pip install .
```

2. Put at least one API key in `~/.env.sys`, for example:

```text
GROQ_API_KEY="..."
OPENROUTER_API_KEY="..."
```

3. Generate `harnessd.key` and `harnessd.crt` at `~/agentic/`:

```sh
sh harnessd/generate-cert.sh YOUR_SERVER_HOSTNAME YOUR_SERVER_IP
```

If you only connect by IP address, pass that IP address for both arguments.
4. Install the public certificate on the iOS simulator or device.
5. Set the service file's `User`, `WorkingDirectory`, `EnvironmentFile`, and `ExecStart` paths to the deployment account. Copy it to `/etc/systemd/system/harnessd.service`, then run:

```sh
sudo systemctl daemon-reload
sudo systemctl start harnessd
sudo systemctl enable harnessd
```

The graded root endpoint is implemented as:

```text
GET / -> UM EECS Agentic harnessd
POST /llmprompt -> SSE chat completion proxy
POST /llmchat -> SSE chat completion proxy with SQLite conversation context keyed by appID
POST /llmclear -> clears SQLite conversation context for the request appID
```
