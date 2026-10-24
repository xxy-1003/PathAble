"""Local standalone execution server for PathAble Cloud Slow-Loop.

Enables full offline execution, test fixture inspection, and judge review
without requiring paid AWS provisioning or internet connectivity.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("pathable.cloud.server")


def main():
    parser = argparse.ArgumentParser(description="PathAble Cloud Slow-Loop Local Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code change")
    args = parser.parse_args()

    # Ensure repository root is on sys.path
    repo_root = Path(__file__).resolve().parents[4]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    logger.info("=" * 65)
    logger.info("PathAble AWS Slow-Loop Service (Local Emulation Mode)")
    logger.info("Binding to: http://%s:%d", args.host, args.port)
    logger.info("Dashboard UI: http://%s:%d/dashboard/", args.host, args.port)
    logger.info("API Docs: http://%s:%d/docs", args.host, args.port)
    logger.info("=" * 65)

    uvicorn.run(
        "production.v3.cloud.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
