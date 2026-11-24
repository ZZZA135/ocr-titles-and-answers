"""本地答案库：SQLite 持久化 + 自动去重 + 模糊检索。"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .match import ScanHit, find_matches, normalize_text, similarity
from .parse import Question

_SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qno TEXT,
    stem TEXT NOT NULL,
    options_json TEXT,
    answer_letter TEXT,
    answer_text TEXT,
    qtype TEXT,
    source TEXT,
    raw TEXT,
    norm_stem TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_norm_stem ON questions(norm_stem);
"""


def resolve_answer_text(letter: Optional[str], options: Dict[str, str],
                        fallback_text: Optional[str] = None) -> Optional[str]:
    """由答案字母还原答案文字；字母不在选项里时保留原文字答案。"""
    if letter:
        letters = [c for c in letter if c in options]
        if letters:
            return "；".join(options[c] for c in letters)
        return fallback_text
    return fallback_text


class AnswerStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ---------------- 写入 ----------------
    @staticmethod
    def _is_duplicate(norm: str, options: Dict[str, str],
                      other_norm: str, other_options: Dict[str, str],
                      threshold: float) -> bool:
        """题干像 + 选项也像才算重复。

        同一题干配不同选项，往往是不同章节/不同版本的题（答案也不一样），
        把它当重复丢掉，那道题就永远查不到答案，所以这里要放过。
        """
        if not other_norm:
            return False
        if similarity(norm, other_norm) < threshold:
            return False
        a = [normalize_text(v) for v in (options or {}).values() if v]
        b = [normalize_text(v) for v in (other_options or {}).values() if v]
        a = [x for x in a if x]
        b = [x for x in b if x]
        if not a or not b:
            return True
        # 逐条找最像的那一项，容忍 OCR 掉字/错字；两边都有多数能配上就算同一题
        matched = sum(1 for x in a if any(similarity(x, y) >= 0.75 for y in b))
        return matched / max(len(a), len(b)) >= 0.6

    def add_questions(self, questions: Iterable[Question],
                      dedupe_threshold: float = 0.90) -> Tuple[int, int]:
        """批量入库，返回 (新增条数, 判重跳过条数)。

        判重时如果库里那条没有答案、而这次导入的带答案，就把答案补进去（不新增记录）。
        """
        added = skipped = 0
        with self._lock:
            existing = [{
                "id": r["id"],
                "norm": r["norm_stem"],
                "options": json.loads(r["options_json"] or "{}"),
                "answer_letter": r["answer_letter"],
                "answer_text": r["answer_text"],
            } for r in self._conn.execute(
                "SELECT id, norm_stem, options_json, answer_letter, answer_text FROM questions")]
            for q in questions:
                norm = normalize_text(q.stem)
                if not norm:
                    skipped += 1
                    continue
                dup = next((e for e in existing
                            if self._is_duplicate(norm, q.options, e["norm"], e["options"],
                                                  dedupe_threshold)), None)
                if dup is not None:
                    skipped += 1
                    if (not dup["answer_letter"] and not dup["answer_text"]) and (q.answer_letter or q.answer_text):
                        answer_text = q.answer_text or resolve_answer_text(q.answer_letter, q.options)
                        self._conn.execute(
                            "UPDATE questions SET answer_letter=?, answer_text=?, options_json=?,"
                            " source=? WHERE id=?",
                            (q.answer_letter, answer_text,
                             json.dumps(q.options or dup["options"], ensure_ascii=False),
                             q.source, dup["id"]),
                        )
                        dup["answer_letter"] = q.answer_letter
                        dup["answer_text"] = answer_text
                        dup["options"] = q.options or dup["options"]
                    continue
                answer_text = q.answer_text or resolve_answer_text(q.answer_letter, q.options)
                cursor = self._conn.execute(
                    "INSERT INTO questions (qno, stem, options_json, answer_letter, answer_text,"
                    " qtype, source, raw, norm_stem, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (q.qno, q.stem, json.dumps(q.options, ensure_ascii=False), q.answer_letter,
                     answer_text, q.qtype, q.source, q.raw, norm,
                     datetime.now().isoformat(timespec="seconds")),
                )
                existing.append({
                    "id": cursor.lastrowid, "norm": norm, "options": dict(q.options),
                    "answer_letter": q.answer_letter, "answer_text": answer_text,
                })
                added += 1
            self._conn.commit()
        return added, skipped

    def update_question(self, qid: int, stem: str, options: Dict[str, str],
                        answer_letter: Optional[str], qno: Optional[str] = None) -> None:
        letter = (answer_letter or "").upper().strip() or None
        answer_text = resolve_answer_text(letter, options)
        with self._lock:
            self._conn.execute(
                "UPDATE questions SET qno=?, stem=?, options_json=?, answer_letter=?,"
                " answer_text=?, norm_stem=? WHERE id=?",
                (qno or "", stem, json.dumps(options, ensure_ascii=False), letter,
                 answer_text, normalize_text(stem), qid),
            )
            self._conn.commit()

    def delete_question(self, qid: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM questions WHERE id=?", (qid,))
            self._conn.commit()

    # ---------------- 读取 ----------------
    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0])

    def _row_to_question(self, row: sqlite3.Row) -> Question:
        return Question(
            qno=row["qno"] or "",
            stem=row["stem"] or "",
            options=json.loads(row["options_json"] or "{}"),
            answer_letter=row["answer_letter"] or None,
            answer_text=row["answer_text"] or None,
            qtype=row["qtype"] or "",
            source=row["source"] or "",
            raw=row["raw"] or "",
        )

    def list_questions(self, keyword: str = "") -> List[Tuple[int, Question]]:
        """按关键词筛题。

        - 空格分隔的多个词要同时命中（AND）；
        - 每个词在题干 / 选项 / 答案文字 / 题号里任意一处命中即可；
        - 不区分大小写。
        """
        tokens = [t for t in (keyword or "").split() if t]
        sql = "SELECT * FROM questions"
        args: list = []
        if tokens:
            clauses = []
            for t in tokens:
                like = f"%{t}%"
                clauses.append("(stem LIKE ? OR options_json LIKE ? OR answer_text LIKE ?"
                               " OR IFNULL(qno,'') LIKE ?)")
                args.extend([like, like, like, like])
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [(r["id"], self._row_to_question(r)) for r in rows]

    def delete_all(self) -> int:
        """清空答案库，返回删掉的条数。"""
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
            self._conn.execute("DELETE FROM questions")
            self._conn.commit()
        return int(n)

    def get_question(self, qid: int) -> Optional[Question]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        return self._row_to_question(row) if row else None

    def search(self, query: str, top_n: int = 3, threshold: float = 0.45) -> List[ScanHit]:
        questions = [q for _, q in self.list_questions()]
        return find_matches(query, questions, top_n=top_n, threshold=threshold)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
