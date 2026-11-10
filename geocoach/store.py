"""SQLite persistence for duels, rounds and guesses."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from geocoach.duels import Duel, Guess, Mode, Round, RoundResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS duels (
    game_id TEXT PRIMARY KEY,
    played_at_ms INTEGER,
    mode TEXT NOT NULL,
    rated INTEGER NOT NULL,
    my_team TEXT,
    won INTEGER,
    my_rating INTEGER,
    opp_rating INTEGER,
    opp_id TEXT,
    map_name TEXT,
    raw TEXT
);
CREATE TABLE IF NOT EXISTS rounds (
    game_id TEXT NOT NULL REFERENCES duels(game_id) ON DELETE CASCADE,
    n INTEGER NOT NULL,
    pano_id TEXT,
    lat REAL, lng REAL, country TEXT,
    heading REAL, pitch REAL, zoom REAL,
    multiplier REAL, healing INTEGER,
    PRIMARY KEY (game_id, n)
);
CREATE TABLE IF NOT EXISTS guesses (
    game_id TEXT NOT NULL REFERENCES duels(game_id) ON DELETE CASCADE,
    n INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    is_me INTEGER NOT NULL,
    lat REAL, lng REAL, distance_m REAL, score INTEGER, time_spent_ms INTEGER,
    guess_country TEXT,
    PRIMARY KEY (game_id, n, player_id)
);
CREATE TABLE IF NOT EXISTS round_results (
    game_id TEXT NOT NULL REFERENCES duels(game_id) ON DELETE CASCADE,
    n INTEGER NOT NULL,
    my_health_before INTEGER, my_health_after INTEGER,
    opp_health_before INTEGER, opp_health_after INTEGER,
    PRIMARY KEY (game_id, n)
);
CREATE INDEX IF NOT EXISTS idx_duels_mode_time ON duels(mode, played_at_ms DESC);
CREATE TABLE IF NOT EXISTS meta_docs (
    doc TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    pages INTEGER NOT NULL,
    ingested_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta_chunks (
    id INTEGER PRIMARY KEY,
    doc TEXT NOT NULL REFERENCES meta_docs(doc) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    country_tags TEXT NOT NULL,
    text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'text'
);
CREATE INDEX IF NOT EXISTS idx_meta_chunks_doc_page ON meta_chunks(doc, page);
CREATE VIRTUAL TABLE IF NOT EXISTS meta_fts USING fts5(
    text, country_tags, content='meta_chunks', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS meta_chunks_ai AFTER INSERT ON meta_chunks BEGIN
    INSERT INTO meta_fts(rowid, text, country_tags) VALUES (new.id, new.text, new.country_tags);
END;
CREATE TRIGGER IF NOT EXISTS meta_chunks_ad AFTER DELETE ON meta_chunks BEGIN
    INSERT INTO meta_fts(meta_fts, rowid, text, country_tags)
    VALUES ('delete', old.id, old.text, old.country_tags);
END;
"""


class Store:
    def __init__(self, path: Path | str = ":memory:"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(meta_chunks)")}
        if "kind" not in cols:
            with self.conn:
                self.conn.execute(
                    "ALTER TABLE meta_chunks ADD COLUMN kind TEXT NOT NULL DEFAULT 'text'"
                )

    def close(self) -> None:
        self.conn.close()

    def has_duel(self, game_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM duels WHERE game_id = ?", (game_id,)).fetchone()
        return row is not None

    def upsert_duel(self, duel: Duel, raw: str | None = None) -> None:
        """Insert or replace a duel and its rounds, guesses and health rows."""
        with self.conn:
            self.conn.execute("DELETE FROM duels WHERE game_id = ?", (duel.game_id,))
            self.conn.execute(
                "INSERT INTO duels VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    duel.game_id,
                    duel.played_at_ms,
                    duel.mode.value,
                    int(duel.rated),
                    duel.my_team,
                    None if duel.won is None else int(duel.won),
                    duel.my_rating,
                    duel.opp_rating,
                    duel.opp_id,
                    duel.map_name,
                    raw,
                ),
            )
            self.conn.executemany(
                "INSERT INTO rounds VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [_round_row(duel.game_id, r) for r in duel.rounds],
            )
            self.conn.executemany(
                "INSERT INTO guesses VALUES (?,?,?,?,?,?,?,?,?,?)",
                [_guess_row(duel.game_id, g) for g in duel.guesses],
            )
            self.conn.executemany(
                "INSERT INTO round_results VALUES (?,?,?,?,?,?)",
                [_result_row(duel.game_id, rr) for rr in duel.round_results],
            )

    def recent_duels(
        self, n: int, modes: Iterable[Mode] | None = None, rated_only: bool = True
    ) -> list[sqlite3.Row]:
        mode_list = [m.value for m in modes] if modes else [m.value for m in Mode]
        marks = ",".join("?" * len(mode_list))
        sql = f"SELECT * FROM duels WHERE mode IN ({marks})"
        params: list = list(mode_list)
        if rated_only:
            sql += " AND rated = 1"
        sql += " ORDER BY played_at_ms DESC LIMIT ?"
        params.append(n)
        return self.conn.execute(sql, params).fetchall()

    def rounds_for(self, game_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM rounds WHERE game_id = ? ORDER BY n", (game_id,)
        ).fetchall()

    def guesses_for(self, game_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM guesses WHERE game_id = ? ORDER BY n, is_me DESC", (game_id,)
        ).fetchall()

    def results_for(self, game_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM round_results WHERE game_id = ? ORDER BY n", (game_id,)
        ).fetchall()


def _round_row(game_id: str, r: Round) -> tuple:
    return (
        game_id, r.number, r.pano_id, r.lat, r.lng, r.country,
        r.heading, r.pitch, r.zoom, r.multiplier, int(r.healing),
    )  # fmt: skip


def _guess_row(game_id: str, g: Guess) -> tuple:
    return (
        game_id, g.round_number, g.player_id, int(g.is_me), g.lat, g.lng,
        g.distance_m, g.score, g.time_spent_ms, g.country,
    )  # fmt: skip


def _result_row(game_id: str, rr: RoundResult) -> tuple:
    return (
        game_id, rr.number, rr.my_health_before, rr.my_health_after,
        rr.opp_health_before, rr.opp_health_after,
    )  # fmt: skip
