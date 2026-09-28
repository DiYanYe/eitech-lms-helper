# -*- coding: utf-8 -*-
"""SQLite 最小存储：下载记录（“跳过已下载”的判断依据之一）。"""
import sqlite3
from datetime import datetime
from pathlib import Path

from app import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    course_id     TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    local_path    TEXT NOT NULL,
    bytes_total   INTEGER,
    status        TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (course_id, relative_path)
);
"""

# 轻量迁移：老库缺列时补齐（不重建表、不清数据）
# remote_mtime = 平台文件上传时间（Unix 秒），下载/更新时写入基线，供时间戳校验比对
_MIGRATIONS = {
    "remote_mtime": "ALTER TABLE downloads ADD COLUMN remote_mtime INTEGER",
}


class Storage:
    def __init__(self, db_path: Path = None):
        path = db_path or config.DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row   # 记录按列名访问（get_record 的消费方依赖）

    def init_schema(self):
        self.conn.executescript(_SCHEMA)
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(downloads)")}
        for col, sql in _MIGRATIONS.items():
            if col not in cols:
                self.conn.execute(sql)
        self.conn.commit()

    def get_record(self, course_id: str, relative_path: str):
        """取下载记录（local_path/bytes_total/remote_mtime）；无记录返回 None。"""
        self.init_schema()
        return self.conn.execute(
            "SELECT local_path, bytes_total, remote_mtime FROM downloads "
            "WHERE course_id=? AND relative_path=? AND status='done'",
            (course_id, relative_path),
        ).fetchone()

    def mark_done(self, course_id: str, relative_path: str, local_path, bytes_total: int,
                  remote_mtime: int = None):
        """记录一次成功下载/更新；remote_mtime 为平台文件上传时间（Unix 秒，未知传 None）。"""
        self.init_schema()
        self.conn.execute(
            "INSERT OR REPLACE INTO downloads "
            "(course_id, relative_path, local_path, bytes_total, status, updated_at, remote_mtime) "
            "VALUES (?,?,?,?,?,?,?)",
            (course_id, relative_path, str(local_path), bytes_total, "done",
             datetime.now().isoformat(timespec="seconds"), remote_mtime),
        )
        self.conn.commit()

    def update_baseline(self, course_id: str, relative_path: str, remote_mtime: int):
        """仅回填平台时间基线（不改动文件与其余记录字段）；记录不存在时不动作。"""
        self.init_schema()
        self.conn.execute(
            "UPDATE downloads SET remote_mtime=? WHERE course_id=? AND relative_path=?",
            (remote_mtime, course_id, relative_path),
        )
        self.conn.commit()

    def clear_course(self, course_id: str):
        """清空某课程下载记录（重测用，不删文件）。"""
        self.init_schema()
        self.conn.execute("DELETE FROM downloads WHERE course_id=?", (course_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()
