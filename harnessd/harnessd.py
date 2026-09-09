from pathlib import Path

from granian.server import Server

if __name__ == "__main__":
    Server(
        "main:app",
        address="0.0.0.0",
        port=443,
        interface="asgi",
        loop="uvloop",
        log_access=True,
        ssl_cert=Path("/home/ubuntu/agentic/harnessd.crt"),
        ssl_key=Path("/home/ubuntu/agentic/harnessd.key"),
        workers=1,
        workers_kill_timeout=3,
        respawn_failed_workers=True,
        respawn_interval=1.0,
    ).serve()
