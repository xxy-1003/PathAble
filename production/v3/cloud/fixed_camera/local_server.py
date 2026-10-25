"""Explicitly local and unauthenticated; SQLite/file persistence by default."""
import argparse
from pathlib import Path
import uvicorn

from .app import create_app
from .local_storage import SQLiteStore, FilePhotos

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path(".test-tmp/fixed-camera"))
    parser.add_argument("--volatile", action="store_true", help="Discard state on exit")
    args = parser.parse_args()
    app = create_app() if args.volatile else create_app(
        SQLiteStore(args.state_dir / "state.sqlite3"), FilePhotos(args.state_dir / "photos"))
    uvicorn.run(app, host="127.0.0.1", port=8002)
