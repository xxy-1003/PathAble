"""Durable localhost development adapters. These do not represent AWS storage."""
import json
from pathlib import Path
import sqlite3
from uuid import UUID

from .models import initial_map
from .storage import Conflict, MemoryPhotos


class SQLiteStore:
    mode = "local-sqlite-not-aws"

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS state (pk TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO state VALUES (?, ?)",
                       ("MAP#prototype", json.dumps(initial_map())))

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def get(self, key):
        with self.connect() as db:
            row = db.execute("SELECT data FROM state WHERE pk=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_new(self, key, value):
        try:
            with self.connect() as db:
                db.execute("INSERT INTO state VALUES (?, ?)", (key, json.dumps(value)))
        except sqlite3.IntegrityError as exc:
            raise Conflict("Resource already exists") from exc

    def get_map(self):
        return self.get("MAP#prototype")

    def list_reports(self, status, limit, cursor):
        with self.connect() as db:
            args = [cursor or ""]
            query = "SELECT pk, data FROM state WHERE pk LIKE 'REPORT#%' AND pk > ?"
            if status:
                query += " AND json_extract(data, '$.status') = ?"
                args.append(status)
            rows = db.execute(query + " ORDER BY pk LIMIT ?", [*args, limit + 1]).fetchall()
        return {"items": [json.loads(row[1]) for row in rows[:limit]],
                "next_cursor": rows[limit - 1][0] if len(rows) > limit else None}

    def review(self, key, report, expected_version, updated_map):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = json.loads(db.execute("SELECT data FROM state WHERE pk=?", (key,)).fetchone()[0])
            current_map = json.loads(db.execute(
                "SELECT data FROM state WHERE pk='MAP#prototype'").fetchone()[0])
            if current["status"] != "PENDING" or current_map["version"] != expected_version:
                raise Conflict("Report or map changed; refresh before reviewing")
            db.execute("UPDATE state SET data=? WHERE pk=?", (json.dumps(report), key))
            if updated_map is not None:
                db.execute("UPDATE state SET data=? WHERE pk='MAP#prototype'", (json.dumps(updated_map),))


class FilePhotos(MemoryPhotos):
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, photo_id):
        return self.root / f"{UUID(str(photo_id))}.jpg"

    def put(self, photo_id, data):
        try:
            with self.path(photo_id).open("xb") as output:
                output.write(data)
        except FileExistsError as exc:
            raise Conflict("Photo already uploaded") from exc

    def get(self, photo_id):
        try:
            return self.path(photo_id).read_bytes()
        except FileNotFoundError as exc:
            raise ValueError("Image has not been uploaded") from exc
