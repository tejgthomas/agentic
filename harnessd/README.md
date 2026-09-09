# harnessd

Python Starlette/Granian implementation of the llmPrompt backend.

## Deploy Notes

1. Copy the top-level `runners.toml` to `/home/ubuntu/agentic/runners.toml`.
2. Put at least one API key in `/home/ubuntu/.env.sys`, for example:

```text
GROQ_API_KEY="..."
OPENROUTER_API_KEY="..."
```

3. Generate `harnessd.key` and `harnessd.crt` at `/home/ubuntu/agentic/`:

```sh
sh harnessd/generate-cert.sh YOUR_SERVER_HOSTNAME YOUR_SERVER_IP
```

If you only connect by IP address, pass that IP address for both arguments.
4. Install the public certificate on the Android device.
5. Copy `harnessd.service` to `/etc/systemd/system/harnessd.service`, then run:

```sh
sudo systemctl daemon-reload
sudo systemctl start harnessd
sudo systemctl enable harnessd
```

The graded root endpoint is implemented as:

```text
GET / -> UM EECS Agentic harnessd
```
