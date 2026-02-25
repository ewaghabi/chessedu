from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import chess
import chess.engine

import app as app_module
import problems
from tests.test_app import make_game_payload


def cp_info(cp: int, pv_uci: str = "e2e4") -> dict:
    return {
        "score": chess.engine.PovScore(chess.engine.Cp(cp), chess.WHITE),
        "pv": [chess.Move.from_uci(pv_uci)],
    }


class SequenceEngine:
    def __init__(self, infos: list[dict]):
        self.infos = infos[:]
        self.calls = 0

    def analyse(self, board: chess.Board, limit: chess.engine.Limit, **kwargs) -> dict:
        del board
        del limit
        del kwargs
        self.calls += 1
        if not self.infos:
            raise RuntimeError("sem infos suficientes")
        return self.infos.pop(0)


class InterruptEngine:
    def __init__(self, interrupt_on_call: int = 3):
        self.calls = 0
        self.interrupt_on_call = interrupt_on_call

    def analyse(self, board: chess.Board, limit: chess.engine.Limit, **kwargs) -> dict:
        del board
        del limit
        del kwargs
        self.calls += 1
        if self.calls >= self.interrupt_on_call:
            raise KeyboardInterrupt()
        return cp_info(0)


class ProblemsTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test_games.db"
        self.db_patch = patch.object(app_module, "DB_PATH", self.db_path)
        self.db_patch.start()
        app_module.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def _seed_game(self, game_id: str, pgn: str) -> None:
        with app_module.db_conn() as conn:
            app_module.upsert_game(
                conn,
                make_game_payload(
                    game_id,
                    pgn=pgn,
                    white="me",
                    black="opp",
                    white_result="win",
                    black_result="resigned",
                    end_time=1700000000,
                ),
            )
            conn.commit()

    def test_schema_migration_is_additive_and_preserves_existing_data(self):
        self._seed_game("g1", "1. e4 e5 2. Nf3 Nc6 1-0")
        with app_module.db_conn() as conn:
            before_games = conn.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"]
            before_positions = conn.execute("SELECT COUNT(*) AS n FROM positions").fetchone()["n"]

            problems.ensure_schema(conn)

            after_games = conn.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"]
            after_positions = conn.execute("SELECT COUNT(*) AS n FROM positions").fetchone()["n"]
            self.assertEqual(before_games, after_games)
            self.assertEqual(before_positions, after_positions)
            self.assertTrue(problems.column_exists(conn, "games", "tactics_last_processed_at"))

    def test_schema_creates_problem_tables_and_expected_columns(self):
        with app_module.db_conn() as conn:
            problems.ensure_schema(conn)
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            self.assertIn("problem_positions", tables)
            self.assertIn("problem_scan_runs", tables)

            cols = {
                row["name"]: row
                for row in conn.execute("PRAGMA table_info(problem_positions)").fetchall()
            }
            self.assertIn("presented_count", cols)
            self.assertIn("correct_count", cols)
            self.assertIn("avg_correct_time_ms", cols)
            self.assertEqual(cols["pv_move_uci"]["notnull"], 1)
            self.assertIn("pv_line_uci", cols)
            self.assertIn("pv_line_san", cols)
            self.assertIn("eval_pv_final", cols)

    def test_parse_one_decimal_positive_validates_format(self):
        self.assertEqual(problems.parse_one_decimal_positive("1.0", "--eval-time"), 10)
        self.assertEqual(problems.parse_one_decimal_positive("3.5", "--eval-delta"), 35)
        with self.assertRaises(ValueError):
            problems.parse_one_decimal_positive("1", "--eval-time")
        with self.assertRaises(ValueError):
            problems.parse_one_decimal_positive("1.00", "--eval-time")
        with self.assertRaises(ValueError):
            problems.parse_one_decimal_positive("0.0", "--eval-time")
        with self.assertRaises(ValueError):
            problems.parse_one_decimal_positive("-1.0", "--eval-time")

    def test_run_batch_respects_max_games(self):
        self._seed_game("g1", "1. e4 e5 2. Nf3 Nc6 1-0")
        self._seed_game("g2", "1. d4 d5 2. c4 e6 1-0")
        engine = SequenceEngine([cp_info(0), cp_info(20), cp_info(450), cp_info(460), cp_info(470)])

        with app_module.db_conn() as conn:
            problems.ensure_schema(conn)
            summary = problems.run_batch(conn, engine, max_games=1, eval_time_tenths=10, eval_delta_tenths=30)
            run_count = conn.execute("SELECT COUNT(*) AS n FROM problem_scan_runs").fetchone()["n"]

        self.assertEqual(summary["games_selected"], 1)
        self.assertEqual(summary["games_processed"], 1)
        self.assertEqual(run_count, 1)

    def test_incremental_skips_same_parameter_pair(self):
        self._seed_game("g1", "1. e4 e5 2. Nf3 Nc6 1-0")
        engine_first = SequenceEngine([cp_info(0), cp_info(20), cp_info(450), cp_info(460), cp_info(470)])
        engine_second = SequenceEngine([])

        with app_module.db_conn() as conn:
            problems.ensure_schema(conn)
            first = problems.run_batch(conn, engine_first, max_games=10, eval_time_tenths=10, eval_delta_tenths=30)
            second = problems.run_batch(conn, engine_second, max_games=10, eval_time_tenths=10, eval_delta_tenths=30)
            positions_count = conn.execute("SELECT COUNT(*) AS n FROM problem_positions").fetchone()["n"]

        self.assertEqual(first["games_processed"], 1)
        self.assertEqual(second["games_selected"], 0)
        self.assertEqual(second["games_processed"], 0)
        self.assertEqual(positions_count, 0)

    def test_incremental_reprocesses_when_parameter_pair_changes(self):
        self._seed_game("g1", "1. e4 e5 2. Nf3 Nc6 1-0")
        engine_first = SequenceEngine([cp_info(0), cp_info(20), cp_info(450), cp_info(460), cp_info(470)])
        engine_second = SequenceEngine([cp_info(0), cp_info(20), cp_info(450), cp_info(460), cp_info(470)])

        with app_module.db_conn() as conn:
            problems.ensure_schema(conn)
            problems.run_batch(conn, engine_first, max_games=10, eval_time_tenths=10, eval_delta_tenths=30)
            second = problems.run_batch(conn, engine_second, max_games=10, eval_time_tenths=10, eval_delta_tenths=20)
            run_count = conn.execute("SELECT COUNT(*) AS n FROM problem_scan_runs").fetchone()["n"]

        self.assertEqual(second["games_processed"], 1)
        self.assertEqual(run_count, 2)

    def test_table_with_game_id_filter_reprocesses_target_game(self):
        self._seed_game("g1", "1. e4 e5 2. Nf3 Nc6 1-0")
        engine_first = SequenceEngine([cp_info(0), cp_info(20), cp_info(450), cp_info(460), cp_info(470)])
        engine_second = SequenceEngine([cp_info(0), cp_info(20), cp_info(450), cp_info(460), cp_info(470)])

        with app_module.db_conn() as conn:
            problems.ensure_schema(conn)
            first = problems.table(
                conn=conn,
                engine=engine_first,
                max_games=10,
                eval_time_tenths=10,
                eval_delta_tenths=30,
                only_pending=True,
                print_table_output=False,
            )
            second = problems.table(
                conn=conn,
                engine=engine_second,
                max_games=1,
                eval_time_tenths=10,
                eval_delta_tenths=30,
                only_pending=False,
                print_table_output=False,
                game_id_filter="g1",
                force_reprocess_single=True,
            )
            run_count = conn.execute("SELECT COUNT(*) AS n FROM problem_scan_runs WHERE game_id = 'g1'").fetchone()["n"]

        self.assertEqual(first["games_processed"], 1)
        self.assertEqual(second["games_selected"], 1)
        self.assertEqual(second["games_processed"], 1)
        self.assertEqual(run_count, 1)

    def test_process_game_inserts_problem_with_table_rules(self):
        self._seed_game(
            "g1",
            "1. e4 {[%clk 0:02:59.9]} 1... e5 {[%clk 0:02:58.0]} 2. Nf3 {[%clk 0:02:57.0]} 2... Nc6 {[%clk 0:02:56.0]} 1-0",
        )
        engine = SequenceEngine(
            [
                [cp_info(0, "e2e4"), cp_info(-20, "d2d4")],
                [cp_info(-350, "e7e5"), cp_info(0, "c7c5")],
                [cp_info(0, "g1f3"), cp_info(-50, "f1c4")],
                [cp_info(-10, "b8c6"), cp_info(-30, "g8f6")],
                [cp_info(0, "d2d4"), cp_info(-20, "c2c4")],
                cp_info(-200, "g1f3"),
            ]
        )

        with app_module.db_conn() as conn:
            problems.ensure_schema(conn)
            row = conn.execute("SELECT id, pgn FROM games WHERE id = 'g1'").fetchone()
            scanned, found = problems.process_game(
                conn=conn,
                engine=engine,
                game_id=row["id"],
                pgn_text=row["pgn"],
                eval_time_tenths=10,
                eval_delta_tenths=30,
            )
            inserted = conn.execute(
                """
                SELECT
                    ply, fen, side_to_move, pv_move_uci, pv_line_uci, pv_line_san, eval_pv_final,
                    presented_count, correct_count, avg_correct_time_ms
                FROM problem_positions
                WHERE game_id = 'g1'
                ORDER BY id ASC
                """
            ).fetchall()

        board_before_black_move = chess.Board()
        board_before_black_move.push_uci("e2e4")

        self.assertEqual(scanned, 4)
        self.assertEqual(found, 1)
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0]["ply"], 2)
        self.assertEqual(inserted[0]["fen"], board_before_black_move.fen())
        self.assertEqual(inserted[0]["side_to_move"], "b")
        self.assertEqual(inserted[0]["pv_move_uci"], "e7e5")
        self.assertEqual(inserted[0]["pv_line_uci"], "e7e5")
        self.assertEqual(inserted[0]["pv_line_san"], "1...e5")
        self.assertIsNotNone(inserted[0]["eval_pv_final"])
        self.assertEqual(inserted[0]["presented_count"], 0)
        self.assertEqual(inserted[0]["correct_count"], 0)
        self.assertEqual(inserted[0]["avg_correct_time_ms"], 0.0)

    def test_process_game_skips_when_played_move_matches_pv(self):
        self._seed_game("g1", "1. e4 e5 2. Nf3 Nc6 1-0")
        engine = SequenceEngine(
            [
                cp_info(0, "e2e4"),
                cp_info(400, "e7e5"),
                cp_info(410, "g1f3"),
                cp_info(420, "b8c6"),
                cp_info(430, "f1b5"),
            ]
        )

        with app_module.db_conn() as conn:
            problems.ensure_schema(conn)
            row = conn.execute("SELECT id, pgn FROM games WHERE id = 'g1'").fetchone()
            scanned, found = problems.process_game(
                conn=conn,
                engine=engine,
                game_id=row["id"],
                pgn_text=row["pgn"],
                eval_time_tenths=10,
                eval_delta_tenths=30,
            )
            count = conn.execute("SELECT COUNT(*) AS n FROM problem_positions WHERE game_id = 'g1'").fetchone()["n"]

        self.assertEqual(scanned, 4)
        self.assertEqual(found, 0)
        self.assertEqual(count, 0)

    def test_score_to_pawns_saturates_mate_scores(self):
        mate_for_white = chess.engine.PovScore(chess.engine.Mate(3), chess.WHITE)
        mate_for_black = chess.engine.PovScore(chess.engine.Mate(-2), chess.WHITE)
        mate_zero = chess.engine.PovScore(chess.engine.Mate(0), chess.WHITE)
        self.assertEqual(problems.score_to_pawns(mate_for_white), 10.0)
        self.assertEqual(problems.score_to_pawns(mate_for_black), -10.0)
        self.assertEqual(problems.score_to_pawns(mate_zero), 10.0)

    def test_pv_line_to_san_converts_legal_variation(self):
        board = chess.Board()
        line = [chess.Move.from_uci(uci) for uci in ["e2e4", "c7c5", "g1f3", "d7d6"]]
        self.assertEqual(problems.pv_line_to_san(board, line), "1. e4 c5 2. Nf3 d6")

    def test_eval_after_pv_line_returns_eval_after_applying_line(self):
        engine = SequenceEngine([cp_info(123, pv_uci="d7d5")])
        result = problems.eval_after_pv_line(engine, chess.Board().fen(), "e2e4", limit_seconds=0.1)
        self.assertEqual(result, 1.23)

    def test_analyze_board_multipv_returns_two_lines(self):
        board = chess.Board()
        engine = SequenceEngine(
            [
                [
                    {
                        "score": chess.engine.PovScore(chess.engine.Cp(120), chess.WHITE),
                        "pv": [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")],
                    },
                    {
                        "score": chess.engine.PovScore(chess.engine.Cp(30), chess.WHITE),
                        "pv": [chess.Move.from_uci("d2d4")],
                    },
                ]
            ]
        )

        info = problems.analyze_board_multipv(engine, board, limit_seconds=0.1, multipv=2)
        self.assertEqual(info["eval_pv1"], 1.2)
        self.assertEqual(info["eval_pv2"], 0.3)
        self.assertEqual(info["pv1_line_uci"], "e2e4 e7e5")

    def test_build_table_rows_backfills_played_eval_from_next_position(self):
        pgn = "1. e4 {[%clk 0:02:59.9]} 1... e5 {[%clk 0:02:59.1]} 1-0"
        engine = SequenceEngine(
            [
                [cp_info(0, "e2e4"), cp_info(-20, "d2d4")],
                [cp_info(150, "e7e5"), cp_info(80, "c7c5")],
                [cp_info(10, "g1f3"), cp_info(-10, "f1c4")],
            ]
        )

        rows = problems.build_table_rows(engine, pgn, eval_time_tenths=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["played_san"], "1.e4")
        self.assertEqual(rows[1]["played_san"], "1...e5")
        self.assertEqual(rows[0]["pv1_line_san"], "1. e4")
        self.assertEqual(rows[1]["pv1_line_san"], "1...e5")
        self.assertEqual(rows[0]["eval_pv1"], 0.0)
        self.assertEqual(rows[0]["eval_pv2"], -0.2)
        self.assertIsNone(rows[0]["eval_anterior"])
        self.assertEqual(rows[0]["eval_played"], 1.5)
        self.assertEqual(rows[0]["clock_seconds"], 179.9)
        self.assertEqual(rows[1]["eval_pv1"], -1.5)
        self.assertEqual(rows[1]["eval_pv2"], -0.8)
        self.assertEqual(rows[1]["eval_anterior"], -0.0)
        self.assertEqual(rows[1]["eval_played"], -0.1)
        self.assertEqual(rows[1]["clock_seconds"], 179.1)
        self.assertEqual(rows[0]["problem"], False)
        self.assertEqual(rows[1]["problem"], False)
        self.assertEqual(rows[0]["c1"], False)
        self.assertEqual(rows[0]["c2"], True)
        self.assertEqual(rows[0]["c3"], False)
        self.assertEqual(rows[0]["c4"], False)
        self.assertEqual(rows[0]["c5"], True)

    def test_build_table_rows_inverts_eval_anterior_from_previous_row(self):
        pgn = "1. e4 1... e5 1-0"
        engine = SequenceEngine(
            [
                [cp_info(80, "e2e4"), cp_info(20, "d2d4")],
                [cp_info(200, "e7e5"), cp_info(100, "c7c5")],
                [cp_info(120, "g1f3"), cp_info(60, "f1c4")],
            ]
        )

        rows = problems.build_table_rows(engine, pgn, eval_time_tenths=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["eval_pv1"], 0.8)
        self.assertEqual(rows[1]["eval_anterior"], -0.8)

    def test_is_problem_candidate_reuses_current_rules(self):
        self.assertTrue(
            problems.is_problem_candidate(
                eval_prev=0.1,
                eval_curr=3.5,
                delta_limit=3.0,
                played_uci="d2d4",
                best_uci="e2e4",
            )
        )
        self.assertFalse(
            problems.is_problem_candidate(
                eval_prev=4.5,
                eval_curr=8.0,
                delta_limit=3.0,
                played_uci="d2d4",
                best_uci="e2e4",
            )
        )
        self.assertFalse(
            problems.is_problem_candidate(
                eval_prev=0.0,
                eval_curr=4.0,
                delta_limit=3.0,
                played_uci="e2e4",
                best_uci="e2e4",
            )
        )

    def test_is_table_problem_candidate_rules(self):
        self.assertEqual(
            problems.evaluate_table_problem_criteria(
                eval_anterior=0.0,
                eval_pv1=3.2,
                eval_pv2=0.4,
                eval_jogado=0.1,
                tempo_restante_s=45.0,
                eval_delta=3.0,
            ),
            {"c1": True, "c2": True, "c3": True, "c4": True, "c5": True, "problem": True},
        )
        self.assertEqual(
            problems.evaluate_table_problem_criteria(
                eval_anterior=0.5,
                eval_pv1=2.0,
                eval_pv2=0.2,
                eval_jogado=0.1,
                tempo_restante_s=45.0,
                eval_delta=3.0,
            ),
            {"c1": False, "c2": True, "c3": False, "c4": False, "c5": True, "problem": False},
        )
        self.assertTrue(
            problems.is_table_problem_candidate(
                eval_anterior=0.0,
                eval_pv1=3.2,
                eval_pv2=0.4,
                eval_jogado=0.1,
                tempo_restante_s=45.0,
                eval_delta=3.0,
            )
        )
        self.assertFalse(
            problems.is_table_problem_candidate(
                eval_anterior=0.5,
                eval_pv1=2.0,
                eval_pv2=0.2,
                eval_jogado=0.1,
                tempo_restante_s=45.0,
                eval_delta=3.0,
            )
        )
        self.assertFalse(
            problems.is_table_problem_candidate(
                eval_anterior=0.0,
                eval_pv1=5.5,
                eval_pv2=1.0,
                eval_jogado=0.2,
                tempo_restante_s=45.0,
                eval_delta=3.0,
            )
        )
        self.assertFalse(
            problems.is_table_problem_candidate(
                eval_anterior=0.0,
                eval_pv1=3.0,
                eval_pv2=1.0,
                eval_jogado=2.7,
                tempo_restante_s=45.0,
                eval_delta=3.0,
            )
        )
        self.assertFalse(
            problems.is_table_problem_candidate(
                eval_anterior=0.0,
                eval_pv1=3.2,
                eval_pv2=0.4,
                eval_jogado=0.1,
                tempo_restante_s=18.0,
                eval_delta=3.0,
            )
        )

    def test_is_relevant_problem_swing_filters_irrelevant_large_same_side_advantage(self):
        self.assertTrue(problems.is_relevant_problem_swing(0.1, 3.5))
        self.assertFalse(problems.is_relevant_problem_swing(4.5, 8.0))
        self.assertTrue(problems.is_relevant_problem_swing(-1.5, 3.0))
        self.assertTrue(problems.is_relevant_problem_swing(-3.0, 0.1))
        self.assertFalse(problems.is_relevant_problem_swing(-9.0, -4.0))

    def test_run_batch_prints_progress(self):
        self._seed_game("g1", "1. e4 e5 2. Nf3 Nc6 1-0")
        engine = SequenceEngine([cp_info(0), cp_info(20), cp_info(450), cp_info(460), cp_info(470)])
        out = io.StringIO()

        with app_module.db_conn() as conn:
            problems.ensure_schema(conn)
            with redirect_stdout(out):
                problems.run_batch(conn, engine, max_games=1, eval_time_tenths=10, eval_delta_tenths=30)

        printed = out.getvalue()
        self.assertIn("\r[1/1]", printed)
        self.assertIn("[1/1]", printed)
        self.assertIn("Analisando 1.e4", printed)
        self.assertIn("problemas=0", printed)
        self.assertIn("concluido", printed)

    def test_run_batch_handles_keyboard_interrupt_without_traceback(self):
        self._seed_game("g1", "1. e4 e5 2. Nf3 Nc6 1-0")
        engine = InterruptEngine(interrupt_on_call=3)

        with app_module.db_conn() as conn:
            problems.ensure_schema(conn)
            out = io.StringIO()
            with redirect_stdout(out):
                summary = problems.run_batch(conn, engine, max_games=1, eval_time_tenths=10, eval_delta_tenths=30)
            runs = conn.execute("SELECT COUNT(*) AS n FROM problem_scan_runs").fetchone()["n"]

        self.assertEqual(summary["interrupted"], 1)
        self.assertEqual(summary["games_processed"], 0)
        self.assertEqual(runs, 0)
        self.assertIn("interrompido", out.getvalue())


if __name__ == "__main__":
    unittest.main()
