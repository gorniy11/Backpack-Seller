"""SQLite storage for inventory, listings, trades and queued notifications."""
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path


class Store:
    TABLES = {"inventory", "listings", "offers", "meta", "outbox"}

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "seller.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        for table in self.TABLES:
            self.db.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, time TEXT, message TEXT)")
        self.db.commit()

    def get(self, table, key, default=None):
        assert table in self.TABLES
        with self.lock:
            row = self.db.execute(f"SELECT data FROM {table} WHERE id=?", (str(key),)).fetchone()
        return json.loads(row[0]) if row else default

    def rows(self, table):
        assert table in self.TABLES
        with self.lock:
            rows = self.db.execute(f"SELECT data FROM {table} ORDER BY rowid DESC").fetchall()
        return [json.loads(r[0]) for r in rows]

    def put(self, table, key, value):
        self.batch([(table, key, value)])

    def batch(self, entries):
        with self.lock, self.db:
            for table, key, value in entries:
                assert table in self.TABLES
                self.db.execute(f"INSERT INTO {table}(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                                (str(key), json.dumps(value, ensure_ascii=False)))

    def delete(self, table, key):
        assert table in self.TABLES
        with self.lock, self.db:
            self.db.execute(f"DELETE FROM {table} WHERE id=?", (str(key),))

    def replace_inventory(self, rows):
        with self.lock, self.db:
            self.db.execute("DELETE FROM inventory")
            self.db.executemany("INSERT INTO inventory(id,data) VALUES(?,?)",
                                [(r["asset_id"], json.dumps(r, ensure_ascii=False)) for r in rows])

    def inventory_rows(self):
        return self.rows("inventory")

    def listings(self):
        return self.rows("listings")

    def offers(self):
        return self.rows("offers")

    def log(self, message):
        # Raw network errors can contain tokens; store only the app's sanitized messages.
        with self.lock, self.db:
            self.db.execute("INSERT INTO logs(time,message) VALUES(?,?)",
                            (datetime.now().astimezone().isoformat(timespec="seconds"), str(message)))
            self.db.execute("DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 2000)")

    def logs(self):
        with self.lock:
            rows = self.db.execute("SELECT time,message FROM logs ORDER BY id DESC LIMIT 300").fetchall()
        return [dict(time=t, message=m) for t, m in rows]

    def close(self):
        with self.lock:
            self.db.close()


class InstanceLock:
    def __init__(self, root):
        import msvcrt
        self.file = open(Path(root) / ".instance", "a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.file.close()
            raise RuntimeError("Программа с этой папкой данных уже запущена.") from None

    def close(self):
        if self.file.closed:
            return
        import msvcrt
        self.file.seek(0)
        msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()
