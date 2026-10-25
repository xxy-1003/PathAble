"""Explicitly local, unauthenticated, volatile development server."""
import uvicorn

from .app import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8002)
