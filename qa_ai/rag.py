"""Local, product-isolated repair-history retrieval with versioned embeddings."""
from __future__ import annotations

import hashlib
import json
import math
from contextlib import closing
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable
import urllib.error
import urllib.request


SHA40 = re.compile(r"^[0-9a-f]{40}$")
SECRET = re.compile(r"(?i)(github_pat_|gh[opusr]_|authorization:|password\s*[:=]|cookie:)")


def error_signature(text: str) -> str:
    normalized = re.sub(r"\b[0-9a-f]{40,64}\b", "<hash>", text.lower())
    normalized = re.sub(r"\d+", "<n>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()[:4096]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class EmbeddingUnavailable(RuntimeError):
    pass


class OllamaEmbedder:
    def __init__(self, model: str = "nomic-embed-text:latest",
                 endpoint: str = "http://127.0.0.1:11434", timeout: int = 30):
        self.model, self.endpoint, self.timeout = model, endpoint.rstrip("/"), timeout

    def __call__(self, text: str) -> list[float]:
        body = json.dumps({"model": self.model, "input": text,
                           "keep_alive": 0}).encode("utf-8")
        request = urllib.request.Request(self.endpoint + "/api/embed", data=body,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                value = json.loads(response.read())
            vector = value["embeddings"][0]
            if not isinstance(vector, list) or not vector:
                raise ValueError
            return [float(item) for item in vector]
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
                urllib.error.URLError) as exc:
            raise EmbeddingUnavailable(type(exc).__name__) from exc


class RepairHistory:
    def __init__(self, path: Path, *, index_name: str = "index-v1-nomic",
                 embedding_model: str = "nomic-embed-text:latest",
                 embedder: Callable[[str], list[float]] | None = None):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.index_name, self.embedding_model = index_name, embedding_model
        self.embedder = embedder or OllamaEmbedder(embedding_model)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS indices(
                  name TEXT PRIMARY KEY, embedding_model TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS repairs(
                  id INTEGER PRIMARY KEY, failure_class TEXT NOT NULL,
                  source_repository TEXT NOT NULL, product_type TEXT NOT NULL,
                  error_signature TEXT NOT NULL, symptoms TEXT NOT NULL,
                  root_cause TEXT NOT NULL, fix_summary TEXT NOT NULL,
                  fix_commit_sha TEXT NOT NULL, regression_result TEXT NOT NULL,
                  index_name TEXT NOT NULL, vector_json TEXT NOT NULL);
            """)
            row = db.execute("SELECT embedding_model FROM indices WHERE name=?",
                             (index_name,)).fetchone()
            if row and row[0] != embedding_model:
                raise ValueError("embedding model/index mismatch")
            db.execute("INSERT OR IGNORE INTO indices(name,embedding_model) VALUES(?,?)",
                       (index_name, embedding_model))
            db.commit()

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def add_verified(self, record: dict[str, str]) -> int:
        required = {"failure_class", "source_repository", "product_type",
                    "error_signature", "symptoms", "root_cause", "fix_summary",
                    "fix_commit_sha", "regression_result"}
        if set(record) != required or any(not isinstance(record[k], str) or not record[k]
                                          for k in required):
            raise ValueError("invalid repair record")
        if SECRET.search(json.dumps(record)):
            raise ValueError("secret-like repair history rejected")
        if not SHA40.fullmatch(record["fix_commit_sha"]):
            raise ValueError("invalid fix commit")
        if record["regression_result"] != "PASS":
            raise ValueError("only regression-verified PASS repairs may be indexed")
        vector = self.embedder(record["error_signature"] + "\n" + record["symptoms"])
        with closing(self._connect()) as db:
            cursor = db.execute("""INSERT INTO repairs(
                failure_class,source_repository,product_type,error_signature,symptoms,
                root_cause,fix_summary,fix_commit_sha,regression_result,index_name,vector_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(record[k] for k in ("failure_class", "source_repository", "product_type",
                      "error_signature", "symptoms", "root_cause", "fix_summary",
                      "fix_commit_sha", "regression_result")) +
                (self.index_name, json.dumps(vector)))
            db.commit()
            return int(cursor.lastrowid)

    def search(self, text: str, *, source_repository: str, product_type: str,
               top_k: int = 3) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            rows = db.execute("""SELECT failure_class,error_signature,symptoms,
                root_cause,fix_summary,fix_commit_sha,regression_result,vector_json
                FROM repairs WHERE index_name=? AND source_repository=?
                AND product_type=? AND regression_result='PASS'""",
                (self.index_name, source_repository, product_type)).fetchall()
        if not rows:
            return []
        query = self.embedder(text)
        norm_q = math.sqrt(sum(x * x for x in query)) or 1.0
        ranked = []
        for row in rows:
            vector = json.loads(row[7])
            if len(vector) != len(query):
                continue
            norm_v = math.sqrt(sum(x * x for x in vector)) or 1.0
            score = sum(a * b for a, b in zip(query, vector)) / (norm_q * norm_v)
            ranked.append({"failure_class": row[0], "error_signature": row[1],
                           "symptoms": row[2], "root_cause": row[3],
                           "fix_summary": row[4], "fix_commit_sha": row[5],
                           "regression_result": row[6], "similarity": round(score, 6)})
        return sorted(ranked, key=lambda item: item["similarity"], reverse=True)[:top_k]
