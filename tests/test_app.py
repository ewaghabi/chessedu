from __future__ import annotations

import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import chess
import requests

import app as app_module

SAMPLE_PGN_RUY = """[Event \"Live Chess\"]
[Site \"Chess.com\"]
[Date \"2024.01.01\"]
[Round \"-\"]
[White \"me\"]
[Black \"opp\"]
[Result \"1-0\"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0
"""

SAMPLE_PGN_QUEEN = """[Event \"Live Chess\"]
[Site \"Chess.com\"]
[Date \"2024.01.02\"]
[Round \"-\"]
[White \"me\"]
[Black \"opp2\"]
[Result \"0-1\"]

1. d4 d5 2. c4 e6 0-1
"""


class DummyResponse:
    def __init__(self, payload, status_code=200, raise_error=None):
        self._payload = payload
        self.status_code = status_code
        self._raise_error = raise_error

    def raise_for_status(self):
        if self._raise_error:
            raise self._raise_error

    def json(self):
        return self._payload


def make_game_payload(
    game_id,
    pgn=SAMPLE_PGN_RUY,
    white="me",
    black="opp",
    white_result="win",
    black_result="checkmated",
    end_time=1700000000,
    time_class="blitz",
):
    return {
        "uuid": game_id,
        "url": f"https://www.chess.com/game/live/{game_id}",
        "end_time": end_time,
        "white": {"username": white, "result": white_result},
        "black": {"username": black, "result": black_result},
        "time_class": time_class,
        "rules": "chess",
        "pgn": pgn,
    }


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test_games.db"
        self.db_patch = patch.object(app_module, "DB_PATH", self.db_path)
        self.db_patch.start()
        app_module.init_db()

        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_app_version_reads_version_file(self):
        expected = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(app_module.app_version(), expected)

    def test_normalize_username_headers_score(self):
        self.assertEqual(app_module.normalize_username("  UserName  "), "username")
        self.assertEqual(app_module.chess_com_headers()["User-Agent"], "chessedu-local-viewer/1.0")
        self.assertEqual(app_module.score_from_result("win"), 1.0)
        self.assertEqual(app_module.score_from_result("agreed"), 0.5)
        self.assertEqual(app_module.score_from_result("stalemate"), 0.5)
        self.assertEqual(app_module.score_from_result("checkmated"), 0.0)

    def test_fetch_archives_and_monthly_games(self):
        captured = []

        def fake_get(url, headers=None, timeout=None):
            captured.append((url, headers, timeout))
            if url.endswith("archives"):
                return DummyResponse({"archives": ["a1", "a2"]})
            return DummyResponse({"games": [{"uuid": "g1"}]})

        with patch.object(app_module.requests, "get", side_effect=fake_get):
            archives = app_module.fetch_archives("me")
            games = app_module.fetch_monthly_games("https://api.chess.com/month")

        self.assertEqual(archives, ["a1", "a2"])
        self.assertEqual(games, [{"uuid": "g1"}])
        self.assertTrue(captured[0][0].endswith("/player/me/games/archives"))
        self.assertEqual(captured[1][0], "https://api.chess.com/month")
        self.assertEqual(captured[0][2], app_module.CHESS_COM_TIMEOUT)

    def test_game_id_from_payload_branches(self):
        self.assertEqual(app_module.game_id_from_payload({"uuid": "u1", "url": "u"}), "u1")
        self.assertEqual(app_module.game_id_from_payload({"url": "https://g"}), "https://g")
        self.assertIsNone(app_module.game_id_from_payload({}))

    def test_parse_game_and_index_and_empty_parse(self):
        indexed = app_module.parse_game_and_index("g1", SAMPLE_PGN_RUY)
        self.assertEqual(len(indexed), 6)
        self.assertEqual(indexed[0][0], 1)
        self.assertEqual(indexed[0][2], "e4")
        self.assertEqual(indexed[0][5], "w")
        self.assertEqual(indexed[1][5], "b")
        self.assertEqual(app_module.parse_game_and_index("g2", ""), [])

    def test_fen_from_move_list_success_and_illegal(self):
        fen = app_module.fen_from_move_list(["e2e4", "e7e5"])
        self.assertIsInstance(fen, str)
        self.assertTrue(fen.startswith("rnbqkbnr"))

        with self.assertRaises(ValueError):
            app_module.fen_from_move_list(["e2e5"])

    def test_validate_color_filter(self):
        self.assertEqual(app_module.validate_color_filter("any"), "any")
        self.assertEqual(app_module.validate_color_filter("white"), "white")
        self.assertEqual(app_module.validate_color_filter("black"), "black")
        self.assertEqual(app_module.validate_color_filter("  WHITE "), "white")
        with self.assertRaises(ValueError):
            app_module.validate_color_filter("blue")

    def test_parse_time_classes(self):
        self.assertEqual(
            app_module.parse_time_classes(None),
            ["blitz", "rapid", "bullet", "outros"],
        )
        self.assertEqual(
            app_module.parse_time_classes(" blitz,rapid,blitz,outros "),
            ["blitz", "rapid", "outros"],
        )
        with self.assertRaises(ValueError):
            app_module.parse_time_classes("")
        with self.assertRaises(ValueError):
            app_module.parse_time_classes("daily")

    def test_settings_helpers_roundtrip(self):
        with sqlite3.connect(app_module.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            app_module.save_setting(conn, "username", "me")
            conn.commit()
            self.assertEqual(app_module.get_setting(conn, "username"), "me")
            self.assertIsNone(app_module.get_setting(conn, "missing"))

    def test_upsert_game_insert_update_and_invalid_payload(self):
        with app_module.db_conn() as conn:
            self.assertFalse(app_module.upsert_game(conn, {"uuid": "g0"}))

            payload = make_game_payload("g1")
            self.assertTrue(app_module.upsert_game(conn, payload))

            count_games = conn.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"]
            count_pos = conn.execute("SELECT COUNT(*) AS n FROM positions WHERE game_id='g1'").fetchone()["n"]
            self.assertEqual(count_games, 1)
            self.assertEqual(count_pos, 6)

            payload_changed = make_game_payload("g1", pgn="[Event \"X\"]\n\n1. e4 1-0\n")
            self.assertTrue(app_module.upsert_game(conn, payload_changed))

            count_pos2 = conn.execute("SELECT COUNT(*) AS n FROM positions WHERE game_id='g1'").fetchone()["n"]
            self.assertEqual(count_pos2, 1)

    def test_index_and_state_endpoints(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"ChessEdu", response.data)

        state = self.client.get("/api/state")
        self.assertEqual(state.status_code, 200)
        payload = state.get_json()
        self.assertEqual(payload["game_count"], 0)
        self.assertIsNone(payload["username"])
        expected = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(payload["version"], expected)

    def test_api_state_infers_username_when_games_exist_without_setting(self):
        with app_module.db_conn() as conn:
            app_module.upsert_game(
                conn,
                make_game_payload("g_state_1", white="me", black="opp", time_class="blitz"),
            )
            app_module.upsert_game(
                conn,
                make_game_payload("g_state_2", white="opp2", black="me", time_class="rapid"),
            )
            conn.commit()

        state = self.client.get("/api/state")
        self.assertEqual(state.status_code, 200)
        payload = state.get_json()
        self.assertEqual(payload["username"], "me")
        self.assertEqual(payload["game_count"], 2)

    def test_api_sync_requires_username(self):
        response = self.client.post("/api/sync", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("username", response.get_json()["error"])

    def test_api_sync_handles_http_error_with_status(self):
        error = requests.HTTPError("boom")
        error.response = SimpleNamespace(status_code=429)

        with patch.object(app_module, "fetch_archives", side_effect=error):
            response = self.client.post("/api/sync", json={"username": "me"})

        self.assertEqual(response.status_code, 502)
        self.assertTrue(response.get_json()["error"].endswith("HTTP 429"))

    def test_api_sync_handles_http_error_without_response(self):
        error = requests.HTTPError("boom")

        with patch.object(app_module, "fetch_archives", side_effect=error):
            response = self.client.post("/api/sync", json={"username": "me"})

        self.assertEqual(response.status_code, 502)
        self.assertTrue(response.get_json()["error"].endswith("HTTP 502"))

    def test_api_sync_handles_request_exception(self):
        with patch.object(app_module, "fetch_archives", side_effect=requests.RequestException("offline")):
            response = self.client.post("/api/sync", json={"username": "me"})

        self.assertEqual(response.status_code, 502)
        self.assertIn("Falha de conexão", response.get_json()["error"])

    def test_api_sync_success_incremental_and_monthly_error(self):
        archives = ["archive://bad", "archive://good"]
        calls = []

        def fake_archives(username):
            self.assertEqual(username, "me")
            return archives

        def fake_monthly(url):
            calls.append(url)
            if url.endswith("bad"):
                raise requests.RequestException("skip")
            return [make_game_payload("g1")]

        with patch.object(app_module, "fetch_archives", side_effect=fake_archives), patch.object(
            app_module, "fetch_monthly_games", side_effect=fake_monthly
        ):
            first = self.client.post("/api/sync", json={"username": "Me"})
            second = self.client.post("/api/sync", json={"username": "me"})

        body_first = first.get_json()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(body_first["username"], "me")
        self.assertEqual(body_first["archives_total"], 2)
        self.assertEqual(body_first["archives_synced_now"], 1)
        self.assertEqual(body_first["games_imported_now"], 1)
        self.assertEqual(body_first["games_total_in_db"], 1)

        body_second = second.get_json()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(body_second["archives_synced_now"], 0)
        self.assertEqual(body_second["games_imported_now"], 0)
        self.assertEqual(body_second["games_total_in_db"], 1)
        self.assertEqual(calls.count("archive://good"), 1)

    def _seed_two_games_for_stats(self):
        with app_module.db_conn() as conn:
            app_module.upsert_game(
                conn,
                make_game_payload(
                    "g1",
                    pgn=SAMPLE_PGN_RUY,
                    white="me",
                    black="opp",
                    white_result="win",
                    black_result="resigned",
                    end_time=1700000001,
                ),
            )
            app_module.upsert_game(
                conn,
                make_game_payload(
                    "g2",
                    pgn=SAMPLE_PGN_QUEEN,
                    white="opp2",
                    black="me",
                    white_result="resigned",
                    black_result="win",
                    end_time=1700000002,
                ),
            )
            conn.commit()

    def _seed_games_for_advanced_filters(self):
        with app_module.db_conn() as conn:
            app_module.upsert_game(
                conn,
                make_game_payload(
                    "g_blitz",
                    pgn=SAMPLE_PGN_RUY,
                    white="me",
                    black="oppb",
                    white_result="win",
                    black_result="resigned",
                    end_time=1700000101,
                    time_class="blitz",
                ),
            )
            app_module.upsert_game(
                conn,
                make_game_payload(
                    "g_rapid_timeout_white",
                    pgn=SAMPLE_PGN_QUEEN,
                    white="me",
                    black="oppr",
                    white_result="timeout",
                    black_result="win",
                    end_time=1700000102,
                    time_class="rapid",
                ),
            )
            app_module.upsert_game(
                conn,
                make_game_payload(
                    "g_daily",
                    pgn=SAMPLE_PGN_RUY,
                    white="oppd",
                    black="me",
                    white_result="resigned",
                    black_result="win",
                    end_time=1700000103,
                    time_class="daily",
                ),
            )
            app_module.upsert_game(
                conn,
                make_game_payload(
                    "g_timeout_black",
                    pgn=SAMPLE_PGN_QUEEN,
                    white="oppx",
                    black="me",
                    white_result="win",
                    black_result="timeout",
                    end_time=1700000104,
                    time_class="bullet",
                ),
            )
            conn.commit()

    def test_api_stats_requires_params(self):
        response = self.client.get("/api/stats")
        self.assertEqual(response.status_code, 400)

    def test_api_stats_returns_move_statistics(self):
        self._seed_two_games_for_stats()
        start_fen = chess.Board().fen()

        response = self.client.get(f"/api/stats?username=me&fen={start_fen}")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        moves = {m["uci"]: m for m in payload["moves"]}
        self.assertEqual(set(moves.keys()), {"e2e4", "d2d4"})
        self.assertEqual(moves["e2e4"]["games"], 1)
        self.assertEqual(moves["d2d4"]["games"], 1)
        self.assertEqual(moves["e2e4"]["win_rate"], 100.0)
        self.assertEqual(moves["d2d4"]["win_rate"], 100.0)

    def test_api_stats_color_filter_white_black_any_and_invalid(self):
        self._seed_two_games_for_stats()
        start_fen = chess.Board().fen()

        any_resp = self.client.get(f"/api/stats?username=me&fen={start_fen}&color=any")
        white_resp = self.client.get(f"/api/stats?username=me&fen={start_fen}&color=white")
        black_resp = self.client.get(f"/api/stats?username=me&fen={start_fen}&color=black")
        invalid_resp = self.client.get(f"/api/stats?username=me&fen={start_fen}&color=invalid")

        self.assertEqual(any_resp.status_code, 200)
        self.assertEqual(white_resp.status_code, 200)
        self.assertEqual(black_resp.status_code, 200)
        self.assertEqual(invalid_resp.status_code, 400)

        any_moves = {m["uci"] for m in any_resp.get_json()["moves"]}
        white_moves = {m["uci"] for m in white_resp.get_json()["moves"]}
        black_moves = {m["uci"] for m in black_resp.get_json()["moves"]}
        self.assertEqual(any_moves, {"e2e4", "d2d4"})
        self.assertEqual(white_moves, {"e2e4"})
        self.assertEqual(black_moves, {"d2d4"})

    def test_api_games_requires_params(self):
        response = self.client.get("/api/games")
        self.assertEqual(response.status_code, 400)

    def test_api_games_lists_games_and_my_result_for_white_and_black(self):
        self._seed_two_games_for_stats()
        start_fen = chess.Board().fen()

        response = self.client.get(f"/api/games?username=me&fen={start_fen}")
        self.assertEqual(response.status_code, 200)
        games = response.get_json()["games"]

        self.assertEqual(len(games), 2)
        result_by_id = {g["id"]: g["my_result"] for g in games}
        self.assertEqual(result_by_id["g1"], "win")
        self.assertEqual(result_by_id["g2"], "win")
        label_by_id = {g["id"]: g["result_label"] for g in games}
        self.assertEqual(label_by_id["g1"], "1-0 (resigned)")
        self.assertEqual(label_by_id["g2"], "0-1 (resigned)")

    def test_api_games_color_filter_white_black_any_and_invalid(self):
        self._seed_two_games_for_stats()
        start_fen = chess.Board().fen()

        any_resp = self.client.get(f"/api/games?username=me&fen={start_fen}&color=any")
        white_resp = self.client.get(f"/api/games?username=me&fen={start_fen}&color=white")
        black_resp = self.client.get(f"/api/games?username=me&fen={start_fen}&color=black")
        invalid_resp = self.client.get(f"/api/games?username=me&fen={start_fen}&color=invalid")

        self.assertEqual(any_resp.status_code, 200)
        self.assertEqual(white_resp.status_code, 200)
        self.assertEqual(black_resp.status_code, 200)
        self.assertEqual(invalid_resp.status_code, 400)

        any_ids = {g["id"] for g in any_resp.get_json()["games"]}
        white_ids = {g["id"] for g in white_resp.get_json()["games"]}
        black_ids = {g["id"] for g in black_resp.get_json()["games"]}
        self.assertEqual(any_ids, {"g1", "g2"})
        self.assertEqual(white_ids, {"g1"})
        self.assertEqual(black_ids, {"g2"})

    def test_api_stats_filters_time_classes_and_timeout(self):
        self._seed_games_for_advanced_filters()
        start_fen = chess.Board().fen()

        only_others = self.client.get(
            f"/api/stats?username=me&fen={start_fen}&time_classes=outros&ignore_timeout_losses=0"
        )
        self.assertEqual(only_others.status_code, 200)
        others_moves = only_others.get_json()["moves"]
        self.assertEqual(len(others_moves), 1)
        self.assertEqual(others_moves[0]["games"], 1)

        no_timeout = self.client.get(
            f"/api/stats?username=me&fen={start_fen}&time_classes=blitz,rapid,bullet,outros&ignore_timeout_losses=1"
        )
        self.assertEqual(no_timeout.status_code, 200)
        filtered_total = sum(move["games"] for move in no_timeout.get_json()["moves"])
        self.assertEqual(filtered_total, 2)

        invalid = self.client.get(f"/api/stats?username=me&fen={start_fen}&time_classes=")
        self.assertEqual(invalid.status_code, 400)

    def test_api_games_filters_time_classes_and_timeout(self):
        self._seed_games_for_advanced_filters()
        start_fen = chess.Board().fen()

        others_only = self.client.get(
            f"/api/games?username=me&fen={start_fen}&time_classes=outros&ignore_timeout_losses=0"
        )
        self.assertEqual(others_only.status_code, 200)
        other_ids = {g["id"] for g in others_only.get_json()["games"]}
        self.assertEqual(other_ids, {"g_daily"})

        no_timeout = self.client.get(
            f"/api/games?username=me&fen={start_fen}&time_classes=blitz,rapid,bullet,outros&ignore_timeout_losses=1"
        )
        self.assertEqual(no_timeout.status_code, 200)
        no_timeout_ids = {g["id"] for g in no_timeout.get_json()["games"]}
        self.assertEqual(no_timeout_ids, {"g_blitz", "g_daily"})

        invalid = self.client.get(f"/api/games?username=me&fen={start_fen}&time_classes=blitz,daily")
        self.assertEqual(invalid.status_code, 400)

    def test_api_count_requires_username_and_applies_filters(self):
        missing = self.client.get("/api/count")
        self.assertEqual(missing.status_code, 400)

        self._seed_games_for_advanced_filters()

        all_games = self.client.get("/api/count?username=me&time_classes=blitz,rapid,bullet,outros")
        self.assertEqual(all_games.status_code, 200)
        self.assertEqual(all_games.get_json()["count"], 4)
        self.assertEqual(all_games.get_json()["problems_count"], 0)

        others_only = self.client.get("/api/count?username=me&time_classes=outros")
        self.assertEqual(others_only.status_code, 200)
        self.assertEqual(others_only.get_json()["count"], 1)
        self.assertEqual(others_only.get_json()["problems_count"], 0)

        no_timeout = self.client.get(
            "/api/count?username=me&time_classes=blitz,rapid,bullet,outros&ignore_timeout_losses=1"
        )
        self.assertEqual(no_timeout.status_code, 200)
        self.assertEqual(no_timeout.get_json()["count"], 2)
        self.assertEqual(no_timeout.get_json()["problems_count"], 0)

    def test_api_count_returns_problems_count_for_filtered_games(self):
        self._seed_games_for_advanced_filters()

        with app_module.db_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS problem_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    ply INTEGER NOT NULL,
                    fen TEXT NOT NULL,
                    side_to_move TEXT NOT NULL,
                    pv_move_uci TEXT NOT NULL,
                    pv_line_uci TEXT,
                    pv_line_san TEXT,
                    eval_pv_final REAL,
                    eval_prev REAL NOT NULL,
                    eval_curr REAL NOT NULL,
                    eval_delta REAL NOT NULL,
                    eval_time_tenths INTEGER NOT NULL,
                    eval_delta_tenths INTEGER NOT NULL,
                    presented_count INTEGER NOT NULL DEFAULT 0,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    avg_correct_time_ms REAL NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                INSERT INTO problem_positions (
                    game_id, ply, fen, side_to_move, pv_move_uci, pv_line_uci, pv_line_san,
                    eval_prev, eval_curr, eval_delta, eval_time_tenths, eval_delta_tenths, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("g_blitz", 1, chess.Board().fen(), "b", "e7e5", "e7e5", "1... e5", 0.0, 3.5, 3.5, 10, 30, 1700000101),
            )
            conn.execute(
                """
                INSERT INTO problem_positions (
                    game_id, ply, fen, side_to_move, pv_move_uci, pv_line_uci, pv_line_san,
                    eval_prev, eval_curr, eval_delta, eval_time_tenths, eval_delta_tenths, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("g_daily", 1, chess.Board().fen(), "b", "d7d5", "d7d5", "1... d5", 0.0, 4.1, 4.1, 10, 30, 1700000103),
            )
            conn.execute(
                """
                INSERT INTO problem_positions (
                    game_id, ply, fen, side_to_move, pv_move_uci, pv_line_uci, pv_line_san,
                    eval_prev, eval_curr, eval_delta, eval_time_tenths, eval_delta_tenths, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "g_timeout_black",
                    1,
                    chess.Board().fen(),
                    "b",
                    "e7e5",
                    "e7e5",
                    "1... e5",
                    0.0,
                    5.0,
                    5.0,
                    10,
                    30,
                    1700000104,
                ),
            )
            conn.commit()

        all_games = self.client.get("/api/count?username=me&time_classes=blitz,rapid,bullet,outros")
        self.assertEqual(all_games.status_code, 200)
        self.assertEqual(all_games.get_json()["count"], 4)
        self.assertEqual(all_games.get_json()["problems_count"], 3)

        others_only = self.client.get("/api/count?username=me&time_classes=outros")
        self.assertEqual(others_only.status_code, 200)
        self.assertEqual(others_only.get_json()["count"], 1)
        self.assertEqual(others_only.get_json()["problems_count"], 1)

        no_timeout = self.client.get(
            "/api/count?username=me&time_classes=blitz,rapid,bullet,outros&ignore_timeout_losses=1"
        )
        self.assertEqual(no_timeout.status_code, 200)
        self.assertEqual(no_timeout.get_json()["count"], 2)
        self.assertEqual(no_timeout.get_json()["problems_count"], 2)

    def test_api_problems_requires_username(self):
        response = self.client.get("/api/problems")
        self.assertEqual(response.status_code, 400)
        self.assertIn("username", response.get_json()["error"])

    def test_api_problems_returns_empty_when_table_is_missing(self):
        self._seed_games_for_advanced_filters()
        response = self.client.get("/api/problems?username=me&time_classes=blitz,rapid,bullet,outros")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["problems"], [])

    def test_api_problems_applies_filters_and_returns_expected_fields(self):
        self._seed_games_for_advanced_filters()
        pgn_invalid_rating = """[Event "Live Chess"]
[Site "Chess.com"]
[Date "2024.01.04"]
[Round "-"]
[White "oppx"]
[Black "me"]
[WhiteElo "abc"]
[BlackElo ""]
[Result "1-0"]

1. d4 d5 1-0
"""
        with app_module.db_conn() as conn:
            app_module.upsert_game(
                conn,
                make_game_payload(
                    "g_timeout_black",
                    pgn=pgn_invalid_rating,
                    white="oppx",
                    black="me",
                    white_result="win",
                    black_result="timeout",
                    end_time=1700000104,
                    time_class="bullet",
                ),
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS problem_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    ply INTEGER NOT NULL,
                    fen TEXT NOT NULL,
                    side_to_move TEXT NOT NULL,
                    pv_move_uci TEXT NOT NULL,
                    pv_line_uci TEXT,
                    pv_line_san TEXT,
                    eval_pv_final REAL,
                    eval_prev REAL NOT NULL,
                    eval_curr REAL NOT NULL,
                    eval_delta REAL NOT NULL,
                    eval_time_tenths INTEGER NOT NULL,
                    eval_delta_tenths INTEGER NOT NULL,
                    presented_count INTEGER NOT NULL DEFAULT 0,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    avg_correct_time_ms REAL NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                INSERT INTO problem_positions (
                    game_id, ply, fen, side_to_move, pv_move_uci, pv_line_uci, pv_line_san,
                    eval_prev, eval_curr, eval_delta, eval_time_tenths, eval_delta_tenths, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("g_blitz", 1, chess.Board().fen(), "w", "e2e4", "e2e4", "1. e4", 0.0, 3.5, 3.5, 10, 30, 1700000101),
            )
            conn.execute(
                """
                INSERT INTO problem_positions (
                    game_id, ply, fen, side_to_move, pv_move_uci, pv_line_uci, pv_line_san,
                    eval_prev, eval_curr, eval_delta, eval_time_tenths, eval_delta_tenths, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("g_daily", 1, chess.Board().fen(), "b", "d7d5", "d7d5", "1... d5", 0.0, 4.1, 4.1, 10, 30, 1700000103),
            )
            conn.execute(
                """
                INSERT INTO problem_positions (
                    game_id, ply, fen, side_to_move, pv_move_uci, pv_line_uci, pv_line_san,
                    eval_prev, eval_curr, eval_delta, eval_time_tenths, eval_delta_tenths, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "g_timeout_black",
                    1,
                    chess.Board().fen(),
                    "b",
                    "e7e5",
                    "e7e5",
                    "1... e5",
                    0.0,
                    5.0,
                    5.0,
                    10,
                    30,
                    1700000104,
                ),
            )
            conn.commit()

        all_problems = self.client.get("/api/problems?username=me&time_classes=blitz,rapid,bullet,outros")
        self.assertEqual(all_problems.status_code, 200)
        payload = all_problems.get_json()
        self.assertEqual(payload["total"], 3)
        self.assertEqual(len(payload["problems"]), 3)
        first = payload["problems"][0]
        self.assertIn("problem_id", first)
        self.assertIn("game_id", first)
        self.assertIn("fen", first)
        self.assertIn("side_to_move", first)
        self.assertIn("pv_move_uci", first)
        self.assertIn("pv_line_uci", first)
        self.assertIn("pv_line_san", first)
        self.assertIn("eval_pv_final", first)
        self.assertIn("eval_prev", first)
        self.assertIn("eval_curr", first)
        self.assertIn("white", first)
        self.assertIn("black", first)
        self.assertIn("white_rating", first)
        self.assertIn("black_rating", first)
        self.assertIn("end_time", first)
        self.assertIn("time_class", first)

        others_only = self.client.get("/api/problems?username=me&time_classes=outros")
        self.assertEqual(others_only.status_code, 200)
        others_payload = others_only.get_json()
        self.assertEqual(others_payload["total"], 1)
        self.assertEqual(others_payload["problems"][0]["game_id"], "g_daily")

        no_timeout = self.client.get(
            "/api/problems?username=me&time_classes=blitz,rapid,bullet,outros&ignore_timeout_losses=1"
        )
        self.assertEqual(no_timeout.status_code, 200)
        no_timeout_payload = no_timeout.get_json()
        no_timeout_ids = {item["game_id"] for item in no_timeout_payload["problems"]}
        self.assertEqual(no_timeout_ids, {"g_blitz", "g_daily"})
        self.assertEqual(no_timeout_payload["total"], 2)
        self.assertIsNone(
            next(item for item in payload["problems"] if item["game_id"] == "g_timeout_black")["white_rating"]
        )
        self.assertIsNone(
            next(item for item in payload["problems"] if item["game_id"] == "g_timeout_black")["black_rating"]
        )

    def test_api_delete_problem_handles_missing_and_success(self):
        self._seed_games_for_advanced_filters()

        missing_table = self.client.delete("/api/problems/1")
        self.assertEqual(missing_table.status_code, 404)

        with app_module.db_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS problem_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    ply INTEGER NOT NULL,
                    fen TEXT NOT NULL,
                    side_to_move TEXT NOT NULL,
                    pv_move_uci TEXT NOT NULL,
                    pv_line_uci TEXT,
                    pv_line_san TEXT,
                    eval_pv_final REAL,
                    eval_prev REAL NOT NULL,
                    eval_curr REAL NOT NULL,
                    eval_delta REAL NOT NULL,
                    eval_time_tenths INTEGER NOT NULL,
                    eval_delta_tenths INTEGER NOT NULL,
                    presented_count INTEGER NOT NULL DEFAULT 0,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    avg_correct_time_ms REAL NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                INSERT INTO problem_positions (
                    game_id, ply, fen, side_to_move, pv_move_uci, pv_line_uci, pv_line_san,
                    eval_prev, eval_curr, eval_delta, eval_time_tenths, eval_delta_tenths, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("g_blitz", 1, chess.Board().fen(), "w", "e2e4", "e2e4", "1. e4", 0.0, 3.5, 3.5, 10, 30, 1700000101),
            )
            conn.commit()
            inserted_id = conn.execute("SELECT id FROM problem_positions LIMIT 1").fetchone()["id"]

        not_found = self.client.delete("/api/problems/999999")
        self.assertEqual(not_found.status_code, 404)

        deleted = self.client.delete(f"/api/problems/{inserted_id}")
        self.assertEqual(deleted.status_code, 200)
        payload = deleted.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["problem_id"], inserted_id)
        self.assertEqual(payload["game_id"], "g_blitz")

        with app_module.db_conn() as conn:
            count = conn.execute("SELECT COUNT(*) AS n FROM problem_positions").fetchone()["n"]
        self.assertEqual(count, 0)

    def test_api_game_not_found_and_found(self):
        missing = self.client.get("/api/game/not-found")
        self.assertEqual(missing.status_code, 404)

        with app_module.db_conn() as conn:
            app_module.upsert_game(conn, make_game_payload("g100"))
            conn.commit()

        found = self.client.get("/api/game/g100")
        self.assertEqual(found.status_code, 200)
        payload = found.get_json()
        self.assertEqual(payload["id"], "g100")
        self.assertIn("pgn", payload)
        self.assertIn("time_class", payload)
        self.assertIn("white_result", payload)
        self.assertIn("black_result", payload)
        self.assertIn("white_rating", payload)
        self.assertIn("black_rating", payload)
        self.assertIn("result_label", payload)
        self.assertEqual(payload["result_label"], "1-0 (resigned)")

    def test_api_fen_validates_input_and_returns_fen(self):
        invalid_type = self.client.post("/api/fen", json={"moves": "e2e4"})
        self.assertEqual(invalid_type.status_code, 400)

        invalid_move = self.client.post("/api/fen", json={"moves": ["e2e5"]})
        self.assertEqual(invalid_move.status_code, 400)

        valid = self.client.post("/api/fen", json={"moves": ["e2e4", "e7e5"]})
        self.assertEqual(valid.status_code, 200)
        self.assertIn("fen", valid.get_json())

    def test_frontend_javascript_has_valid_syntax(self):
        node_path = shutil.which("node")
        if not node_path:
            self.skipTest("node não disponível")

        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [node_path, "--check", str(root / "static" / "app.js")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_frontend_artifacts_are_present_and_wired(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "app.js").read_text(encoding="utf-8")
        style = (root / "static" / "style.css").read_text(encoding="utf-8")
        chess_vendor = (root / "static" / "vendor" / "chessjs" / "chess.min.js").read_text(encoding="utf-8")

        self.assertIn('id="sync-btn"', template)
        self.assertIn('class="btn-spinner"', template)
        self.assertIn('class="status-message"', template)
        self.assertIn('id="db-count"', template)
        self.assertIn('id="app-version"', template)
        self.assertIn('id="color-filter"', template)
        self.assertIn('id="color-filter-label"', template)
        self.assertIn('id="auto-flip"', template)
        self.assertIn('id="time-outros"', template)
        self.assertIn('id="ignore-timeout-losses"', template)
        self.assertIn('id="filtered-count"', template)
        self.assertIn("Partidas: 0", template)
        self.assertIn("Problemas: 0", template)
        self.assertIn('id="go-problems-btn"', template)
        self.assertIn('id="problem-modal-overlay"', template)
        self.assertIn('id="problem-board"', template)
        self.assertIn('id="problem-next-btn"', template)
        self.assertIn('id="problem-repeat-btn"', template)
        self.assertIn('id="problem-skip-btn"', template)
        self.assertIn('id="problem-delete-btn"', template)
        self.assertIn('id="problem-delete-confirm-overlay"', template)
        self.assertIn('id="problem-delete-confirm-btn"', template)
        self.assertIn('id="problem-delete-cancel-btn"', template)
        self.assertIn("ChessEdu", template)
        self.assertNotIn("Chess.com Opening Explorer", template)
        self.assertNotIn("Entenda seus erros de abertura", template)
        self.assertNotIn('id="games-btn"', template)
        self.assertIn('id="game-meta"', template)
        self.assertIn('id="player-top"', template)
        self.assertIn('id="player-bottom"', template)
        self.assertNotIn('id="position-info"', template)
        self.assertIn('id="replay-first"', template)
        self.assertIn('id="replay-prev"', template)
        self.assertIn('id="replay-next"', template)
        self.assertIn('id="replay-last"', template)
        self.assertIn('id="reset-btn">|&lt;<', template)
        self.assertIn('id="back-btn">&lt;<', template)
        self.assertIn("moves-toolbar", template)
        self.assertIn("vendor/chessboardjs/chessboard-1.0.0.min.css", template)
        self.assertIn("vendor/chessjs/chess.min.js", template)
        self.assertIn("vendor/jquery/jquery-3.7.1.min.js", template)
        self.assertIn("vendor/chessboardjs/chessboard-1.0.0.min.js", template)
        self.assertIn("function doSync()", script)
        self.assertIn("function setSyncLoading(isLoading)", script)
        self.assertIn("function updateVersion(version)", script)
        self.assertIn("function updateColorFilterLabel()", script)
        self.assertIn("function refreshFilteredCount()", script)
        self.assertIn("function updateFilteredCount(count, problemsCount = 0)", script)
        self.assertIn("function openProblemsSession()", script)
        self.assertIn("function onProblemDrop(source, target)", script)
        self.assertIn("function onProblemDragStart(source, piece)", script)
        self.assertIn("function onProblemSnapEnd()", script)
        self.assertIn("function applyProblemDragCursor(pieceCode)", script)
        self.assertIn("function resetProblemCursor()", script)
        self.assertIn("function showNextProblem()", script)
        self.assertIn("function repeatCurrentProblem()", script)
        self.assertIn("function closeProblemModal()", script)
        self.assertIn("function deleteCurrentProblem()", script)
        self.assertIn("function openProblemDeleteConfirm()", script)
        self.assertIn("function ensureProblemBoardVisible()", script)
        self.assertIn("startProblemTimer()", script)
        self.assertIn("stopProblemTimer()", script)
        self.assertIn("function applyBoardOrientation()", script)
        self.assertIn("function buildPlayerLabel(name, rating)", script)
        self.assertIn("function updateReplayButtons()", script)
        self.assertIn("function renderReplayPosition()", script)
        self.assertIn("function formatMoveLabel(", script)
        self.assertIn("game-result-win", script)
        self.assertIn("game-result-loss", script)
        self.assertIn("game-result-draw", script)
        self.assertIn("el.username.disabled = (data.game_count || 0) > 0", script)
        self.assertIn("let colorFilter = \"any\"", script)
        self.assertIn("let selectedTimeClasses = new Set", script)
        self.assertIn("move-item", script)
        self.assertIn("colorFilter =", script)
        self.assertIn("time_classes=", script)
        self.assertIn("ignore_timeout_losses=", script)
        self.assertIn("await refreshFromPosition(true)", script)
        self.assertIn("Chessboard(\"board\"", script)
        self.assertIn("pieceTheme:", script)
        self.assertIn("window.addEventListener(\"error\"", script)
        self.assertIn("window.addEventListener(\"unhandledrejection\"", script)
        self.assertIn("var Chess=", chess_vendor)
        self.assertNotIn("export const Chess", chess_vendor)
        self.assertIn(".badge", style)
        self.assertIn(".btn-spinner", style)
        self.assertIn(".status-message.success", style)
        self.assertIn(".app-version", style)
        self.assertIn(".game-meta", style)
        self.assertIn(".player-tag", style)
        self.assertIn(".replay-actions", style)
        self.assertIn(".moves-toolbar", style)
        self.assertIn(".board-wrap", style)
        self.assertIn(".filter-block", style)
        self.assertIn(".check-row", style)
        self.assertIn(".filter-count", style)
        self.assertIn(".problem-modal-overlay", style)
        self.assertIn(".problem-modal", style)
        self.assertIn(".problem-feedback.success", style)
        self.assertIn(".problem-btn-success", style)
        self.assertIn(".problem-btn-danger", style)
        self.assertIn(".problem-btn-neutral", style)
        self.assertIn(".problem-delete-btn", style)
        self.assertIn(".problem-confirm-overlay", style)
        self.assertIn(".problem-confirm-modal", style)
        self.assertIn(".game-result-win", style)
        self.assertIn(".game-result-loss", style)
        self.assertIn(".game-result-draw", style)
        self.assertIn("--win-rate", style)
        self.assertIn(".move-item", style)


if __name__ == "__main__":
    unittest.main()
