"""Admin-only personal backups, isolated from public assets and the RAG index.

Metadata is stored in a dedicated SQLite database even when business data uses
MySQL. Only the authenticated /api/private-knowledge/ routes expose this store.
No uploaded path, file ID or content enters the business schema or exports.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import uuid
import zipfile

MAX_FILE = 256 * 1024 * 1024
MAX_FILES = 100
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".log", ".yaml", ".yml"}


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class PrivateConflict(ValueError):
    pass


class PrivateKnowledge:
    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve() / "private_knowledge"
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.files = self.root / "files"
        self.files.mkdir(mode=0o700, exist_ok=True)
        self.previews = self.root / "previews"
        self.database = self.root / "vault.sqlite3"
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS private_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL, category TEXT NOT NULL, tags TEXT NOT NULL,
                    content TEXT NOT NULL, created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL, deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS private_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL REFERENCES private_entries(id),
                    file_name TEXT NOT NULL, stored_name TEXT NOT NULL UNIQUE,
                    file_size INTEGER NOT NULL, sha256 TEXT NOT NULL,
                    created_by TEXT NOT NULL, created_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_private_files_entry ON private_files(entry_id);
                CREATE INDEX IF NOT EXISTS idx_private_entries_deleted ON private_entries(deleted_at,id);
            """)
        if os.name != "nt":
            self.database.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def _entry(db, rid, deleted=False):
        row = db.execute(
            "SELECT * FROM private_entries WHERE id=?", (int(rid),)
        ).fetchone()
        if not row or bool(row["deleted_at"]) != bool(deleted):
            raise ValueError("私人资料不存在或状态已改变，请刷新")
        return dict(row)

    @staticmethod
    def _version(entry, payload):
        if payload.get("expected_updated_at") != entry["updated_at"]:
            raise PrivateConflict(
                "私人资料已被修改，请刷新后重新编辑，避免覆盖其他修改"
            )

    @staticmethod
    def _text(value, limit, label, required=False):
        if not isinstance(value, str):
            raise ValueError(label + "必须是文本")
        text = value.strip()
        if (required and not text) or len(text) > limit or "\x00" in text:
            raise ValueError(
                label
                + f"格式无效：最多{limit}字，不允许空字符"
                + ("，且不能为空" if required else "")
            )
        return text

    @staticmethod
    def _detail(db, entry):
        files = [
            dict(row)
            for row in db.execute(
                "SELECT id,entry_id,file_name,file_size,sha256,created_by,created_at "
                "FROM private_files WHERE entry_id=? AND deleted_at IS NULL ORDER BY id",
                (entry["id"],),
            )
        ]
        return {**entry, "files": files}

    def detail(self, rid):
        with self.connect() as db:
            return self._detail(db, self._entry(db, rid))

    def listing(self, query):
        q = self._text(query.get("q", [""])[0], 200, "检索内容")
        page = max(1, int(query.get("page", ["1"])[0]))
        size = 20
        trash = query.get("trash") == ["1"]
        where = "e.deleted_at IS NOT NULL" if trash else "e.deleted_at IS NULL"
        args = []
        if q:
            where += " AND (instr(lower(e.title||' '||e.category||' '||e.tags||' '||e.content),lower(?))>0 OR EXISTS(SELECT 1 FROM private_files f WHERE f.entry_id=e.id AND f.deleted_at IS NULL AND instr(lower(f.file_name),lower(?))>0))"
            args = [q, q]
        with self.connect() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM private_entries e WHERE " + where, args
            ).fetchone()[0]
            page = min(page, max(1, (total + size - 1) // size))
            data = [
                self._detail(db, dict(row))
                for row in db.execute(
                    "SELECT e.* FROM private_entries e WHERE "
                    + where
                    + " ORDER BY e.updated_at DESC,e.id DESC LIMIT ? OFFSET ?",
                    (*args, size, (page - 1) * size),
                )
            ]
        return {
            "data": data,
            "total": total,
            "page": page,
            "page_size": size,
            "trash": trash,
        }

    def save(self, payload, user):
        record = payload.get("record")
        if not isinstance(record, dict) or set(record) - {
            "title",
            "category",
            "tags",
            "content",
        }:
            raise ValueError("私人资料字段无效")
        values = [
            self._text(record.get(k, ""), limit, label, k == "title")
            for k, limit, label in [
                ("title", 191, "标题"),
                ("category", 191, "分类"),
                ("tags", 1024, "关键词"),
                ("content", 100000, "思考与备注"),
            ]
        ]
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rid = payload.get("id")
            now = stamp()
            if rid:
                self._version(self._entry(db, rid), payload)
                db.execute(
                    "UPDATE private_entries SET title=?,category=?,tags=?,content=?,updated_by=?,updated_at=? WHERE id=?",
                    (*values, user["username"], now, int(rid)),
                )
            else:
                rid = db.execute(
                    "INSERT INTO private_entries (title,category,tags,content,created_by,created_at,updated_by,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (*values, user["username"], now, user["username"], now),
                ).lastrowid
            db.commit()
            return self._detail(db, self._entry(db, rid))

    def upload(self, query, stream, size, user, safe_filename):
        if not 0 < size <= MAX_FILE:
            raise ValueError("私人附件必须非空，单文件最多256 MB")
        name = safe_filename(query.get("name", [""])[0])
        rid = int(query.get("id", ["0"])[0])
        version = {"expected_updated_at": query.get("expected_updated_at", [None])[0]}
        # Validate before reading a potentially large request, then recheck under
        # the write lock after receiving it. Concurrent edits never get overwritten.
        with self.connect() as db:
            self._version(self._entry(db, rid), version)
        suffix = Path(name).suffix.lower()
        target = self.files / (uuid.uuid4().hex + suffix)
        digest = hashlib.sha256()
        committed = False
        try:
            with target.open("xb") as output:
                if os.name != "nt":
                    target.chmod(0o600)
                remain = size
                while remain:
                    block = stream.read(min(remain, 1024 * 1024))
                    if not block:
                        raise ValueError("私人附件上传不完整")
                    output.write(block)
                    digest.update(block)
                    remain -= len(block)
            if suffix in IMAGE_EXT:
                from PIL import Image

                with Image.open(target) as image:
                    image.verify()
            with self.lock, self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._version(self._entry(db, rid), version)
                count = db.execute(
                    "SELECT COUNT(*) FROM private_files WHERE entry_id=? AND deleted_at IS NULL",
                    (rid,),
                ).fetchone()[0]
                if count >= MAX_FILES:
                    raise ValueError("每条私人资料最多保存100个附件，请新建另一条资料")
                now = stamp()
                db.execute(
                    "INSERT INTO private_files (entry_id,file_name,stored_name,file_size,sha256,created_by,created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        rid,
                        name,
                        target.name,
                        size,
                        digest.hexdigest(),
                        user["username"],
                        now,
                    ),
                )
                db.execute(
                    "UPDATE private_entries SET updated_by=?,updated_at=? WHERE id=?",
                    (user["username"], now, rid),
                )
                db.commit()
                committed = True
                return self._detail(db, self._entry(db, rid))
        finally:
            if not committed:
                target.unlink(missing_ok=True)

    def change(self, action, payload, user):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            entry = self._entry(db, payload["id"], deleted=action == "restore")
            self._version(entry, payload)
            now = stamp()
            if action in ("delete", "restore"):
                db.execute(
                    "UPDATE private_entries SET deleted_at=? WHERE id=?",
                    (now if action == "delete" else None, entry["id"]),
                )
            elif action == "file-delete":
                row = db.execute(
                    "SELECT * FROM private_files WHERE id=? AND entry_id=? AND deleted_at IS NULL",
                    (int(payload["file_id"]), entry["id"]),
                ).fetchone()
                if not row:
                    raise ValueError("附件不属于当前私人资料或已移除")
                db.execute(
                    "UPDATE private_files SET deleted_at=? WHERE id=?", (now, row["id"])
                )
            else:
                raise ValueError("未知私人资料操作")
            db.execute(
                "UPDATE private_entries SET updated_by=?,updated_at=? WHERE id=?",
                (user["username"], now, entry["id"]),
            )
            db.commit()
            return {"ok": True}

    def file(self, rid):
        with self.connect() as db:
            row = db.execute(
                "SELECT f.* FROM private_files f JOIN private_entries e ON e.id=f.entry_id "
                "WHERE f.id=? AND f.deleted_at IS NULL AND e.deleted_at IS NULL",
                (int(rid),),
            ).fetchone()
        if not row:
            raise ValueError("私人附件不存在或已移除")
        path = (self.files / row["stored_name"]).resolve()
        if not path.is_relative_to(self.files.resolve()) or not path.is_file():
            raise ValueError("私人附件原文件不存在")
        return dict(row), path

    @contextmanager
    def backup(self):
        """Consistent metadata and original files; includes the private recycle bin."""
        with tempfile.TemporaryDirectory(prefix="backup-", dir=self.root) as folder:
            root = Path(folder)
            with self.lock, self.connect() as source:
                database = root / "vault.sqlite3"
                with sqlite3.connect(database) as destination:
                    source.backup(destination)
                target = root / "private-knowledge.zip"
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(database, "private_knowledge/vault.sqlite3")
                    for row in source.execute("SELECT stored_name FROM private_files"):
                        path = (self.files / row["stored_name"]).resolve()
                        if (
                            not path.is_relative_to(self.files.resolve())
                            or not path.is_file()
                        ):
                            raise ValueError(
                                "部分私人附件缺失，备份未完成，请检查磁盘文件"
                            )
                        archive.write(path, "private_knowledge/files/" + path.name)
                    archive.writestr(
                        "恢复说明.txt",
                        "此压缩包包含管理员私人资料、移除的附件及回收站内容，请妥善保管。\n恢复时先停止服务，备份并移走现有 private_knowledge 目录，再将压缩包中的 private_knowledge 放回实际 AOI_DATA 目录。\n不要直接覆盖正在运行的 SQLite 数据库。\n",
                    )
            yield target


def serve_file(handler, store, query):
    """Call only AFTER live administrator authentication, including cache hits."""
    from urllib.parse import quote
    import io

    record, path = store.file(query.get("id", ["0"])[0])
    mode = query.get("mode", ["original"])[0]
    suffix = path.suffix.lower()
    if mode == "preview":
        from media_preview import render_preview

        data, _ = render_preview(path, store.previews, record["file_name"])
        handler.reply(data, ctype="image/jpeg")
        return
    if mode == "view" and suffix in IMAGE_EXT:
        from PIL import Image, ImageOps

        with Image.open(path) as source:
            source.seek(0)
            image = ImageOps.exif_transpose(source)
            if image.mode not in ("1", "L", "LA", "RGB", "RGBA", "I;16", "I"):
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG")
        handler.reply(output.getvalue(), ctype="image/png")
        return
    if mode == "view" and suffix not in TEXT_EXT | {".pdf"}:
        raise ValueError("该附件请查看首页预览或下载原文件")
    if mode not in ("original", "view"):
        raise ValueError("未知私人附件访问方式")
    if mode == "view" and suffix in TEXT_EXT and path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("文本较大，请下载原文件查看")
    ctype = (
        "application/octet-stream"
        if mode == "original"
        else "application/pdf" if suffix == ".pdf" else "text/plain; charset=utf-8"
    )
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(path.stat().st_size))
    handler.send_header("Cache-Control", "no-store, private")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Security-Policy", "sandbox; default-src 'none'")
    handler.send_header("Referrer-Policy", "no-referrer")
    if mode == "original":
        handler.send_header(
            "Content-Disposition",
            "attachment; filename*=UTF-8''" + quote(record["file_name"]),
        )
    handler.end_headers()
    with path.open("rb") as source:
        shutil.copyfileobj(source, handler.wfile)
