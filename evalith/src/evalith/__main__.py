"""Run the Evalith phase-1 service on the host.

    python -m evalith --port 8090

The default bind address is 127.0.0.1. Local project paths are read with host
permissions; do not bind to a public interface.
"""

from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalith phase-1 service")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    from .config import settings_from_env

    settings = settings_from_env()
    host = args.host or settings.api_host
    if host not in {"127.0.0.1", "::1", "localhost"} and os.environ.get(
        "EVALITH_ALLOW_REMOTE"
    ) != "1":
        parser.error(
            "refusing to bind a non-loopback address; this service can read local "
            "project paths. Set EVALITH_ALLOW_REMOTE=1 only on a trusted network."
        )
    # Keep callbacks and same-origin checks aligned with the CLI-selected port.
    os.environ["EVALITH_API_PORT"] = str(args.port or settings.api_port)
    uvicorn.run(
        "evalith.api:app",
        host=host,
        port=args.port or settings.api_port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
