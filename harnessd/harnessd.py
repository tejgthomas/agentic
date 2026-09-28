import os
from pathlib import Path

from granian.server import Server

DEPLOY_ROOT = Path(__file__).resolve().parent.parent
SSL_CERT = Path(os.environ.get("HARNESSD_SSL_CERT", DEPLOY_ROOT / "harnessd.crt"))
SSL_KEY = Path(os.environ.get("HARNESSD_SSL_KEY", DEPLOY_ROOT / "harnessd.key"))

if __name__ == "__main__":
    Server(
        "main:app",
        address="0.0.0.0",
        port=443,
        interface="asgi",
        loop="uvloop",
        log_access=True,
        ssl_cert=SSL_CERT,
        ssl_key=SSL_KEY,
        workers=1,
        workers_kill_timeout=3,
        respawn_failed_workers=True,
        respawn_interval=1.0,
    ).serve()
