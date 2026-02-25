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
        return 0.0

    cp = white_score.score()
    if cp is None:
        return 0.0
    return cp / 100.0


def analyze_board(engine: Any, board: chess.Board, limit_seconds: float) -> tuple[float, str | None]:
    info = engine.analyse(board, chess.engine.Limit(time=limit_seconds))
    score = info.get("score")
    if score is None:
        raise ValueError("Stockfish retornou análise sem score.")

    eval_pawns = score_to_pawns(score)
    pv = info.get("pv") or []
    pv_first = pv[0].uci() if pv else None
    return eval_pawns, pv_first


def process_game(
    conn: sqlite3.Connection,
    engine: Any,
    game_id: str,
    pgn_text: str,
    eval_time_tenths: int,
    eval_delta_tenths: int,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    parsed_game = chess.pgn.read_game(io.StringIO(pgn_text or ""))
    if parsed_game is None:
        return 0, 0

    eval_time_s = eval_time_tenths / 10.0
    delta_limit = eval_delta_tenths / 10.0
    now = int(time.time())

    board = parsed_game.board()
    prev_eval, _ = analyze_board(engine, board, eval_time_s)

    scanned = 0
    found = 0
    ply = 1
    for move in parsed_game.mainline_moves():
        board.push(move)
        curr_eval, pv_first = analyze_board(engine, board, eval_time_s)
        scanned += 1

        eval_delta = abs(curr_eval - prev_eval)
        if eval_delta > delta_limit and pv_first:
            side_to_move = "w" if board.turn == chess.WHITE else "b"
            conn.execute(
                """
                INSERT INTO problem_positions (
                    game_id, ply, fen, side_to_move, pv_move_uci,
                    eval_prev, eval_curr, eval_delta,
                    eval_time_tenths, eval_delta_tenths, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    ply,
                    board.fen(),
                    side_to_move,
                    pv_first,
                    prev_eval,
                    curr_eval,
                    eval_delta,
                    eval_time_tenths,
                    eval_delta_tenths,
                    now,
                ),
            )
            found += 1

        if progress_callback and (scanned == 1 or scanned % PROGRESS_UPDATE_EVERY_PLIES == 0):
            progress_callback(scanned, found)

        prev_eval = curr_eval
        ply += 1

    if progress_callback:
        progress_callback(scanned, found)

    return scanned, found


def run_batch(
    conn: sqlite3.Connection,
    engine: Any,
    max_games: int,
    eval_time_tenths: int,
    eval_delta_tenths: int,
) -> dict[str, int]:
    games = pending_games(conn, eval_time_tenths, eval_delta_tenths, max_games)
    total = len(games)
    summary = {
        "games_selected": total,
        "games_processed": 0,
        "positions_scanned": 0,
        "problems_found": 0,
        "games_failed": 0,
        "interrupted": 0,
    }

    for idx, row in enumerate(games, start=1):
        game_id = row["id"]
        game_start = time.time()
        progress_state = {"scanned": 0, "found": 0}
        last_line_len = 0

        def print_progress(scanned: int, found: int, suffix: str = "") -> None:
            nonlocal last_line_len
            progress_state["scanned"] = scanned
            progress_state["found"] = found
            elapsed = time.time() - game_start
            line = f"[{idx}/{total}] game={game_id} plies={scanned} problemas={found} tempo={elapsed:.1f}s{suffix}"
            if len(line) < last_line_len:
                line = line + (" " * (last_line_len - len(line)))
            last_line_len = len(line)
            print(f"\r{line}", end="", flush=True)

        try:
            conn.execute("BEGIN")
            print_progress(0, 0, " iniciando")
            scanned, found = process_game(
                conn=conn,
                engine=engine,
                game_id=game_id,
                pgn_text=row["pgn"],
                eval_time_tenths=eval_time_tenths,
                eval_delta_tenths=eval_delta_tenths,
                progress_callback=print_progress,
            )
            now = int(time.time())
            conn.execute(
                """
                INSERT INTO problem_scan_runs (
                    game_id, eval_time_tenths, eval_delta_tenths,
                    processed_at, positions_scanned, problems_found
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (game_id, eval_time_tenths, eval_delta_tenths, now, scanned, found),
            )
            conn.execute(
                "UPDATE games SET tactics_last_processed_at = ? WHERE id = ?",
                (now, game_id),
            )
            conn.commit()

            summary["games_processed"] += 1
            summary["positions_scanned"] += scanned
            summary["problems_found"] += found

            print_progress(scanned, found, " concluido")
            print(flush=True)
        except KeyboardInterrupt:
            conn.rollback()
            summary["interrupted"] = 1
            summary["positions_scanned"] += progress_state["scanned"]
            summary["problems_found"] += progress_state["found"]
            print_progress(progress_state["scanned"], progress_state["found"], " interrompido")
            print(flush=True)
            break
        except Exception as exc:  # pragma: no cover - defensive path
            conn.rollback()
            summary["games_failed"] += 1
            print_progress(progress_state["scanned"], progress_state["found"], f" erro={exc}")
            print(flush=True)

    return summary


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

        engine = chess.engine.SimpleEngine.popen_uci(args.stockfish_path)
        try:
            summary = run_batch(
                conn=conn,
                engine=engine,
                max_games=args.max_games,
                eval_time_tenths=eval_time_tenths,
                eval_delta_tenths=eval_delta_tenths,
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
