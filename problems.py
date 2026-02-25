from __future__ import annotations

import argparse
import io
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

import chess
import chess.engine
import chess.pgn

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "games.db"
DEFAULT_STOCKFISH_PATH = "/opt/homebrew/bin/stockfish"
MATE_PAWN_VALUE = 10.0
PROGRESS_UPDATE_EVERY_PLIES = 5
LARGE_ADVANTAGE_PAWNS = 4.0


def parse_one_decimal_positive(raw: str, flag_name: str) -> int:
    value = (raw or "").strip()
    if not re.fullmatch(r"\d+\.\d", value):
        raise ValueError(f"{flag_name} deve ter 1 casa decimal (ex: 1.0).")

    as_float = float(value)
    if as_float <= 0:
        raise ValueError(f"{flag_name} deve ser maior que zero.")
    return int(round(as_float * 10))


def db_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def ensure_schema(conn: sqlite3.Connection) -> None:
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
        CREATE TABLE IF NOT EXISTS problem_scan_runs (
            game_id TEXT NOT NULL,
            eval_time_tenths INTEGER NOT NULL,
            eval_delta_tenths INTEGER NOT NULL,
            processed_at INTEGER NOT NULL,
            positions_scanned INTEGER NOT NULL,
            problems_found INTEGER NOT NULL,
            PRIMARY KEY (game_id, eval_time_tenths, eval_delta_tenths),
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_problem_positions_game_id ON problem_positions(game_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_problem_positions_fen ON problem_positions(fen)")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_problem_positions_eval_params
        ON problem_positions(eval_time_tenths, eval_delta_tenths)
        """
    )

    if not column_exists(conn, "games", "tactics_last_processed_at"):
        conn.execute("ALTER TABLE games ADD COLUMN tactics_last_processed_at INTEGER")

    conn.commit()


def pending_games(
    conn: sqlite3.Connection, eval_time_tenths: int, eval_delta_tenths: int, max_games: int
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT g.id, g.pgn
        FROM games g
        LEFT JOIN problem_scan_runs r
          ON r.game_id = g.id
         AND r.eval_time_tenths = ?
         AND r.eval_delta_tenths = ?
        WHERE r.game_id IS NULL
        ORDER BY g.end_time DESC, g.id ASC
        LIMIT ?
        """,
        (eval_time_tenths, eval_delta_tenths, max_games),
    ).fetchall()


def total_pending_games(conn: sqlite3.Connection, eval_time_tenths: int, eval_delta_tenths: int) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM games g
        LEFT JOIN problem_scan_runs r
          ON r.game_id = g.id
         AND r.eval_time_tenths = ?
         AND r.eval_delta_tenths = ?
        WHERE r.game_id IS NULL
        """,
        (eval_time_tenths, eval_delta_tenths),
    ).fetchone()
    return int(row["n"])


def score_to_pawns(score: chess.engine.PovScore) -> float:
    white_score = score.white()
    mate = white_score.mate()
    if mate is not None:
        if mate > 0:
            return MATE_PAWN_VALUE
        if mate < 0:
            return -MATE_PAWN_VALUE
        # Mate(0) still represents a forced mate endpoint in this line; avoid
        # collapsing it to equality, which would hide decisive outcomes.
        return MATE_PAWN_VALUE

    cp = white_score.score()
    if cp is None:
        return 0.0
    return cp / 100.0


def pv_line_to_uci(pv: list[chess.Move]) -> str | None:
    if not pv:
        return None
    return " ".join(move.uci() for move in pv)


def pv_line_to_san(board: chess.Board, pv: list[chess.Move]) -> str | None:
    if not pv:
        return None
    try:
        return board.variation_san(pv)
    except ValueError:
        return None


def eval_after_pv_line(engine: Any, fen: str, pv_line_uci: str | None, limit_seconds: float) -> float | None:
    if not pv_line_uci:
        return None

    board = chess.Board(fen)
    for raw_move in pv_line_uci.split():
        try:
            move = chess.Move.from_uci(raw_move)
        except ValueError:
            return None
        if move not in board.legal_moves:
            return None
        board.push(move)

    eval_after, _, _, _ = analyze_board(engine, board, limit_seconds)
    return eval_after


def analyze_board(engine: Any, board: chess.Board, limit_seconds: float) -> tuple[float, str | None, str | None, str | None]:
    info = engine.analyse(board, chess.engine.Limit(time=limit_seconds))
    score = info.get("score")
    if score is None:
        raise ValueError("Stockfish retornou análise sem score.")

    eval_pawns = score_to_pawns(score)
    pv = info.get("pv") or []
    pv_first = pv[0].uci() if pv else None
    pv_line_uci = pv_line_to_uci(pv)
    pv_line_san = pv_line_to_san(board, pv)
    return eval_pawns, pv_first, pv_line_uci, pv_line_san


def analyze_board_multipv(engine: Any, board: chess.Board, limit_seconds: float, multipv: int = 2) -> dict[str, Any]:
    infos = engine.analyse(board, chess.engine.Limit(time=limit_seconds), multipv=multipv)
    if not isinstance(infos, list):
        infos = [infos]

    first = infos[0] if infos else {}
    second = infos[1] if len(infos) > 1 else {}

    first_score = first.get("score")
    second_score = second.get("score")
    eval_pv1 = score_to_pawns(first_score) if first_score is not None else None
    eval_pv2 = score_to_pawns(second_score) if second_score is not None else None

    first_pv = first.get("pv") or []
    return {
        "eval_pv1": eval_pv1,
        "eval_pv2": eval_pv2,
        "pv1_line_uci": pv_line_to_uci(first_pv),
        "pv1_line_san": pv_line_to_san(board, first_pv),
    }


def eval_for_side_to_move(eval_white: float | None, side_to_move: str) -> float | None:
    if eval_white is None:
        return None
    return eval_white if side_to_move == "w" else -eval_white


def build_table_rows(
    engine: Any,
    pgn_text: str,
    eval_time_tenths: int,
    eval_delta_tenths: int = 30,
    progress_callback: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    parsed_game = chess.pgn.read_game(io.StringIO(pgn_text or ""))
    if parsed_game is None:
        return []

    eval_time_s = eval_time_tenths / 10.0
    delta_limit = eval_delta_tenths / 10.0
    board = parsed_game.board()
    rows: list[dict[str, Any]] = []

    node = parsed_game
    for move in parsed_game.mainline_moves():
        move_number = board.fullmove_number
        move_san = board.san(move)
        if board.turn == chess.WHITE:
            progress_text = f"Analisando {move_number}.{move_san}"
        else:
            progress_text = f"Analisando {move_number}...{move_san}"
        if progress_callback:
            progress_callback(progress_text)

        next_node = node.variation(0) if node.variations else None
        clock_seconds = next_node.clock() if next_node is not None else None
        side_to_move = "w" if board.turn == chess.WHITE else "b"
        multipv_info = analyze_board_multipv(engine, board, eval_time_s, multipv=2)
        raw_eval_pv1 = multipv_info["eval_pv1"]
        raw_eval_pv2 = multipv_info["eval_pv2"]
        row = {
            "fen": board.fen(),
            "played_san": progress_text.replace("Analisando ", "", 1),
            "eval_pv1": eval_for_side_to_move(raw_eval_pv1, side_to_move),
            "eval_pv2": eval_for_side_to_move(raw_eval_pv2, side_to_move),
            "pv1_line_uci": multipv_info["pv1_line_uci"],
            "pv1_line_san": multipv_info["pv1_line_san"],
            "eval_anterior": (-rows[-1]["eval_pv1"] if rows and rows[-1]["eval_pv1"] is not None else None),
            "eval_played": None,
            "clock_seconds": clock_seconds,
            "played_uci": move.uci(),
            "problem": False,
            "side_to_move": side_to_move,
        }
        if rows:
            rows[-1]["eval_played"] = eval_for_side_to_move(raw_eval_pv1, rows[-1]["side_to_move"])
        rows.append(row)
        board.push(move)
        if next_node is not None:
            node = next_node

    if rows:
        final_info = analyze_board_multipv(engine, board, eval_time_s, multipv=2)
        rows[-1]["eval_played"] = eval_for_side_to_move(final_info["eval_pv1"], rows[-1]["side_to_move"])

    for row in rows:
        criteria = evaluate_table_problem_criteria(
            eval_anterior=row.get("eval_anterior"),
            eval_pv1=row.get("eval_pv1"),
            eval_pv2=row.get("eval_pv2"),
            eval_jogado=row.get("eval_played"),
            tempo_restante_s=row.get("clock_seconds"),
            eval_delta=delta_limit,
        )
        row["c1"] = criteria["c1"]
        row["c2"] = criteria["c2"]
        row["c3"] = criteria["c3"]
        row["c4"] = criteria["c4"]
        row["c5"] = criteria["c5"]
        row["problem"] = criteria["problem"]

    return rows


def first_move_from_pv_line(pv_line_uci: str | None) -> str | None:
    if not pv_line_uci:
        return None
    first = pv_line_uci.split(" ", 1)[0].strip()
    return first or None


def table_row_to_problem_insert_payload(
    engine: Any,
    row: dict[str, Any],
    game_id: str,
    ply: int,
    eval_time_tenths: int,
    eval_delta_tenths: int,
    created_at: int,
) -> tuple[Any, ...] | None:
    if not row.get("problem"):
        return None

    side_to_move = row.get("side_to_move")
    fen = row.get("fen")
    eval_prev = row.get("eval_anterior")
    eval_curr = row.get("eval_played")
    pv_line_uci = row.get("pv1_line_uci")
    pv_move_uci = first_move_from_pv_line(pv_line_uci)

    if side_to_move not in {"w", "b"}:
        return None
    if not fen or eval_prev is None or eval_curr is None or not pv_move_uci:
        return None

    eval_prev_white = eval_prev if side_to_move == "w" else -eval_prev
    eval_curr_white = eval_curr if side_to_move == "w" else -eval_curr
    eval_delta = abs(eval_curr_white - eval_prev_white)

    pv_line_san = row.get("pv1_line_san")
    if pv_line_san is None:
        board = chess.Board(fen)
        pv_moves: list[chess.Move] = []
        if pv_line_uci:
            for raw_move in pv_line_uci.split():
                try:
                    move = chess.Move.from_uci(raw_move)
                except ValueError:
                    pv_moves = []
                    break
                if move not in board.legal_moves:
                    pv_moves = []
                    break
                pv_moves.append(move)
                board.push(move)
        pv_line_san = pv_line_to_san(chess.Board(fen), pv_moves) if pv_moves else None
    eval_pv_final = eval_after_pv_line(engine, fen, pv_line_uci, eval_time_tenths / 10.0)

    return (
        game_id,
        ply,
        fen,
        side_to_move,
        pv_move_uci,
        pv_line_uci,
        pv_line_san,
        eval_pv_final,
        eval_prev_white,
        eval_curr_white,
        eval_delta,
        eval_time_tenths,
        eval_delta_tenths,
        created_at,
    )


def format_table_eval(eval_value: float | None) -> str:
    if eval_value is None:
        return "-"
    return f"{eval_value:+.2f}"


def truncate_for_table(text: str | None, max_chars: int = 30) -> str:
    value = (text or "").strip()
    if not value:
        return "-"
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 3]}..."


def format_clock_seconds(clock_seconds: float | None) -> str:
    if clock_seconds is None:
        return "-"
    return f"{clock_seconds:.1f}"


def print_game_table(game_id: str, rows: list[dict[str, Any]]) -> None:
    print(f"\nTabela game={game_id}")
    print(
        f"{'idx':>4} {'fen':<30} {'jogado':<12} {'eval_anterior':>13} {'eval_pv1':>10} {'eval_pv2':>10} "
        f"{'eval_jogado':>12} {'tempo_restante_s':>16} {'c1':>4} {'c2':>4} {'c3':>4} {'c4':>4} {'c5':>4} "
        f"{'problema':>8} {'pv1':<30}"
    )
    if not rows:
        print(
            f"{'-':>4} {'-':<30} {'-':<12} {'-':>13} {'-':>10} {'-':>10} {'-':>12} {'-':>16} {'-':>4} {'-':>4} {'-':>4} "
            f"{'-':>4} {'-':>4} {'-':>8} {'-':<30}"
        )
        return

    for idx, row in enumerate(rows, start=1):
        fen_short = truncate_for_table(row["fen"], 30)
        played_short = truncate_for_table(row.get("played_san"), 12)
        pv1_short = truncate_for_table(row["pv1_line_san"], 30)
        c1_marker = "X" if row.get("c1") else "-"
        c2_marker = "X" if row.get("c2") else "-"
        c3_marker = "X" if row.get("c3") else "-"
        c4_marker = "X" if row.get("c4") else "-"
        c5_marker = "X" if row.get("c5") else "-"
        problem_marker = "X" if row.get("problem") else "-"
        print(
            f"{idx:>4} {fen_short:<30} {played_short:<12} {format_table_eval(row.get('eval_anterior')):>13} {format_table_eval(row['eval_pv1']):>10} "
            f"{format_table_eval(row['eval_pv2']):>10} {format_table_eval(row['eval_played']):>12} "
            f"{format_clock_seconds(row.get('clock_seconds')):>16} {c1_marker:>4} {c2_marker:>4} {c3_marker:>4} "
            f"{c4_marker:>4} {c5_marker:>4} {problem_marker:>8} {pv1_short:<30}"
        )


def clear_game_scan_state(
    conn: sqlite3.Connection,
    game_id: str,
    eval_time_tenths: int,
    eval_delta_tenths: int,
) -> None:
    conn.execute(
        """
        DELETE FROM problem_positions
        WHERE game_id = ?
          AND eval_time_tenths = ?
          AND eval_delta_tenths = ?
        """,
        (game_id, eval_time_tenths, eval_delta_tenths),
    )
    conn.execute(
        """
        DELETE FROM problem_scan_runs
        WHERE game_id = ?
          AND eval_time_tenths = ?
          AND eval_delta_tenths = ?
        """,
        (game_id, eval_time_tenths, eval_delta_tenths),
    )


def table(
    conn: sqlite3.Connection,
    engine: Any,
    max_games: int,
    eval_time_tenths: int,
    eval_delta_tenths: int,
    only_pending: bool = False,
    print_table_output: bool = False,
    game_id_filter: str | None = None,
    force_reprocess_single: bool = False,
) -> dict[str, int]:
    if game_id_filter:
        games = conn.execute(
            """
            SELECT id, pgn
            FROM games
            WHERE id = ?
            LIMIT 1
            """,
            (game_id_filter,),
        ).fetchall()
    elif only_pending:
        games = pending_games(conn, eval_time_tenths, eval_delta_tenths, max_games)
    else:
        games = conn.execute(
            """
            SELECT id, pgn
            FROM games
            ORDER BY end_time DESC, id ASC
            LIMIT ?
            """,
            (max_games,),
        ).fetchall()

    summary = {
        "games_selected": len(games),
        "games_processed": 0,
        "positions_scanned": 0,
        "problems_found": 0,
        "games_failed": 0,
        "interrupted": 0,
    }

    total = len(games)
    for idx, row in enumerate(games, start=1):
        game_id = row["id"]
        game_start = time.time()
        progress_state = {"last_text": "iniciando", "scanned": 0, "found": 0}
        last_progress_len = 0

        def print_progress(text: str) -> None:
            nonlocal last_progress_len
            progress_state["last_text"] = text
            line = f"[{idx}/{total}] game={game_id} {text}"
            if len(line) < last_progress_len:
                line = line + (" " * (last_progress_len - len(line)))
            last_progress_len = len(line)
            print(f"\r{line}", end="", flush=True)

        try:
            conn.execute("BEGIN")
            if force_reprocess_single and game_id_filter:
                clear_game_scan_state(
                    conn=conn,
                    game_id=game_id,
                    eval_time_tenths=eval_time_tenths,
                    eval_delta_tenths=eval_delta_tenths,
                )
            rows = build_table_rows(
                engine,
                row["pgn"],
                eval_time_tenths,
                eval_delta_tenths=eval_delta_tenths,
                progress_callback=print_progress,
            )
            now = int(time.time())
            found = 0
            for ply, table_row in enumerate(rows, start=1):
                payload = table_row_to_problem_insert_payload(
                    engine=engine,
                    row=table_row,
                    game_id=game_id,
                    ply=ply,
                    eval_time_tenths=eval_time_tenths,
                    eval_delta_tenths=eval_delta_tenths,
                    created_at=now,
                )
                if payload is None:
                    continue
                conn.execute(
                    """
                    INSERT INTO problem_positions (
                        game_id, ply, fen, side_to_move, pv_move_uci, pv_line_uci, pv_line_san,
                        eval_pv_final, eval_prev, eval_curr, eval_delta,
                        eval_time_tenths, eval_delta_tenths, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
                found += 1

            conn.execute(
                """
                INSERT INTO problem_scan_runs (
                    game_id, eval_time_tenths, eval_delta_tenths,
                    processed_at, positions_scanned, problems_found
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (game_id, eval_time_tenths, eval_delta_tenths, now, len(rows), found),
            )
            conn.execute(
                "UPDATE games SET tactics_last_processed_at = ? WHERE id = ?",
                (now, game_id),
            )
            conn.commit()

            summary["games_processed"] += 1
            summary["positions_scanned"] += len(rows)
            summary["problems_found"] += found
            progress_state["scanned"] = len(rows)
            progress_state["found"] = found

            if last_progress_len:
                elapsed = time.time() - game_start
                done_line = (
                    f"[{idx}/{total}] game={game_id} concluido "
                    f"plies={len(rows)} problemas={found} tempo={elapsed:.1f}s"
                )
                if len(done_line) < last_progress_len:
                    done_line = done_line + (" " * (last_progress_len - len(done_line)))
                print(f"\r{done_line}", flush=True)

            if print_table_output:
                print_game_table(game_id, rows)
        except KeyboardInterrupt:
            conn.rollback()
            summary["interrupted"] = 1
            if last_progress_len:
                elapsed = time.time() - game_start
                interrupted_line = (
                    f"[{idx}/{total}] game={game_id} interrompido "
                    f"ultimo='{progress_state['last_text']}' tempo={elapsed:.1f}s"
                )
                if len(interrupted_line) < last_progress_len:
                    interrupted_line = interrupted_line + (" " * (last_progress_len - len(interrupted_line)))
                print(f"\r{interrupted_line}", flush=True)
            break
        except Exception as exc:  # pragma: no cover - defensive path
            conn.rollback()
            if last_progress_len:
                elapsed = time.time() - game_start
                error_line = f"[{idx}/{total}] game={game_id} erro={exc} tempo={elapsed:.1f}s"
                if len(error_line) < last_progress_len:
                    error_line = error_line + (" " * (last_progress_len - len(error_line)))
                print(f"\r{error_line}", flush=True)
            summary["games_failed"] += 1

    return summary


def is_relevant_problem_swing(eval_prev: float, eval_curr: float) -> bool:
    if abs(eval_prev) >= LARGE_ADVANTAGE_PAWNS and abs(eval_curr) >= LARGE_ADVANTAGE_PAWNS and (eval_prev * eval_curr) > 0:
        return False
    return True


def is_problem_candidate(
    eval_prev: float,
    eval_curr: float,
    delta_limit: float,
    played_uci: str | None,
    best_uci: str | None,
) -> bool:
    eval_delta = abs(eval_curr - eval_prev)
    played = (played_uci or "").lower()
    best = (best_uci or "").lower()
    is_missed_chance = bool(best) and played != best
    return eval_delta > delta_limit and is_missed_chance and is_relevant_problem_swing(eval_prev, eval_curr)


def evaluate_table_problem_criteria(
    eval_anterior: float | None,
    eval_pv1: float | None,
    eval_pv2: float | None,
    eval_jogado: float | None,
    tempo_restante_s: float | None,
    eval_delta: float,
) -> dict[str, bool]:
    result = {
        "c1": False,
        "c2": False,
        "c3": False,
        "c4": False,
        "c5": False,
        "problem": False,
    }
    if eval_pv1 is not None and eval_anterior is not None:
        result["c1"] = (eval_pv1 - eval_anterior) >= eval_delta
    if eval_pv1 is not None:
        result["c2"] = -1.0 <= eval_pv1 <= 5.0
    if eval_pv1 is not None and eval_pv2 is not None:
        result["c3"] = (eval_pv1 - eval_pv2) > (eval_delta * 0.75)
    if eval_pv1 is not None and eval_jogado is not None:
        result["c4"] = (eval_pv1 - eval_jogado) > (eval_delta * 0.75)
    if tempo_restante_s is not None:
        result["c5"] = tempo_restante_s > 20.0
    result["problem"] = all((result["c1"], result["c2"], result["c3"], result["c4"], result["c5"]))
    return result


def is_table_problem_candidate(
    eval_anterior: float | None,
    eval_pv1: float | None,
    eval_pv2: float | None,
    eval_jogado: float | None,
    tempo_restante_s: float | None,
    eval_delta: float,
) -> bool:
    criteria = evaluate_table_problem_criteria(
        eval_anterior=eval_anterior,
        eval_pv1=eval_pv1,
        eval_pv2=eval_pv2,
        eval_jogado=eval_jogado,
        tempo_restante_s=tempo_restante_s,
        eval_delta=eval_delta,
    )
    return criteria["problem"]


def process_game(
    conn: sqlite3.Connection,
    engine: Any,
    game_id: str,
    pgn_text: str,
    eval_time_tenths: int,
    eval_delta_tenths: int,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    rows = build_table_rows(
        engine=engine,
        pgn_text=pgn_text,
        eval_time_tenths=eval_time_tenths,
        eval_delta_tenths=eval_delta_tenths,
    )
    now = int(time.time())
    found = 0
    for ply, row in enumerate(rows, start=1):
        payload = table_row_to_problem_insert_payload(
            engine=engine,
            row=row,
            game_id=game_id,
            ply=ply,
            eval_time_tenths=eval_time_tenths,
            eval_delta_tenths=eval_delta_tenths,
            created_at=now,
        )
        if payload is None:
            continue
        conn.execute(
            """
            INSERT INTO problem_positions (
                game_id, ply, fen, side_to_move, pv_move_uci, pv_line_uci, pv_line_san,
                eval_pv_final, eval_prev, eval_curr, eval_delta,
                eval_time_tenths, eval_delta_tenths, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        found += 1

    if progress_callback:
        progress_callback(len(rows), found)
    return len(rows), found


def run_batch(
    conn: sqlite3.Connection,
    engine: Any,
    max_games: int,
    eval_time_tenths: int,
    eval_delta_tenths: int,
) -> dict[str, int]:
    return table(
        conn=conn,
        engine=engine,
        max_games=max_games,
        eval_time_tenths=eval_time_tenths,
        eval_delta_tenths=eval_delta_tenths,
        only_pending=True,
        print_table_output=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch de extração de posições-problema com Stockfish.")
    parser.add_argument("--max-games", type=int, required=True, help="Quantidade máxima de jogos para processar.")
    parser.add_argument("--eval-time", required=True, help="Tempo por lance em segundos com 1 decimal (ex: 1.0).")
    parser.add_argument("--eval-delta", required=True, help="Delta mínimo de eval em peões com 1 decimal (ex: 3.0).")
    parser.add_argument(
        "--stockfish-path",
        default=DEFAULT_STOCKFISH_PATH,
        help=f"Caminho do binário do Stockfish (default: {DEFAULT_STOCKFISH_PATH}).",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help=f"Caminho do SQLite (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--tbl",
        action="store_true",
        help="Modo tabela: analisa partidas com MultiPV=2 e imprime tabela por posição.",
    )
    parser.add_argument(
        "--game-id",
        help="Processa apenas o game_id informado (força reprocessamento desse jogo para os parâmetros).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.max_games <= 0:
        print("--max-games deve ser maior que zero.")
        return 2

    try:
        eval_time_tenths = parse_one_decimal_positive(args.eval_time, "--eval-time")
        eval_delta_tenths = parse_one_decimal_positive(args.eval_delta, "--eval-delta")
    except ValueError as exc:
        print(str(exc))
        return 2

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Banco não encontrado: {db_path}")
        return 2

    started = time.time()
    with db_conn(db_path) as conn:
        ensure_schema(conn)
        engine = chess.engine.SimpleEngine.popen_uci(args.stockfish_path)
        try:
            if args.game_id:
                selected = conn.execute("SELECT id FROM games WHERE id = ? LIMIT 1", (args.game_id,)).fetchone()
                if selected is None:
                    print(f"game_id não encontrado: {args.game_id}", flush=True)
                    return 2
                print(
                    "Iniciando batch (game único):",
                    f"game_id={args.game_id}",
                    f"eval_time={eval_time_tenths / 10:.1f}",
                    f"eval_delta={eval_delta_tenths / 10:.1f}",
                    sep=" ",
                    flush=True,
                )
                summary = table(
                    conn=conn,
                    engine=engine,
                    max_games=1,
                    eval_time_tenths=eval_time_tenths,
                    eval_delta_tenths=eval_delta_tenths,
                    only_pending=False,
                    print_table_output=args.tbl,
                    game_id_filter=args.game_id,
                    force_reprocess_single=True,
                )
            else:
                pending = total_pending_games(conn, eval_time_tenths, eval_delta_tenths)
                target = min(args.max_games, pending)
                print(
                    "Iniciando batch:",
                    f"max_games={args.max_games}",
                    f"pendentes={pending}",
                    f"alvo={target}",
                    f"eval_time={eval_time_tenths / 10:.1f}",
                    f"eval_delta={eval_delta_tenths / 10:.1f}",
                    sep=" ",
                    flush=True,
                )

                if target == 0:
                    print("Nenhum jogo pendente para os parâmetros informados.", flush=True)
                    return 0

                summary = table(
                    conn=conn,
                    engine=engine,
                    max_games=args.max_games,
                    eval_time_tenths=eval_time_tenths,
                    eval_delta_tenths=eval_delta_tenths,
                    only_pending=True,
                    print_table_output=args.tbl,
                )
        finally:
            engine.quit()

    elapsed_total = time.time() - started
    if summary["interrupted"]:
        print("Execução interrompida pelo usuário (Ctrl+C).", flush=True)
    print(
        "Resumo:",
        f"selecionados={summary['games_selected']}",
        f"processados={summary['games_processed']}",
        f"falhas={summary['games_failed']}",
        f"plies={summary['positions_scanned']}",
        f"problemas={summary['problems_found']}",
        f"tempo_total={elapsed_total:.1f}s",
        sep=" ",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
