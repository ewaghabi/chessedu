import io
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

import chess
import chess.pgn
import requests
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "games.db"
VERSION_PATH = BASE_DIR / "VERSION"
CHESS_COM_TIMEOUT = 20

app = Flask(__name__)


CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archives (
    archive_url TEXT PRIMARY KEY,
    synced_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    url TEXT,
    end_time INTEGER,
    white TEXT NOT NULL,
    black TEXT NOT NULL,
    white_result TEXT,
    black_result TEXT,
    white_score REAL NOT NULL,
    black_score REAL NOT NULL,
    time_class TEXT,
    rules TEXT,
    pgn TEXT NOT NULL,
    imported_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_games_white ON games(white);
CREATE INDEX IF NOT EXISTS idx_games_black ON games(black);

CREATE TABLE IF NOT EXISTS positions (
    game_id TEXT NOT NULL,
    ply INTEGER NOT NULL,
    fen TEXT NOT NULL,
    move_san TEXT NOT NULL,
    move_uci TEXT NOT NULL,
    next_fen TEXT NOT NULL,
    side_to_move TEXT NOT NULL,
    PRIMARY KEY (game_id, ply),
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_positions_fen ON positions(fen);
CREATE INDEX IF NOT EXISTS idx_positions_game ON positions(game_id);
"""


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def init_db() -> None:
    with closing(db_conn()) as conn:
        conn.executescript(CREATE_TABLES_SQL)
        conn.commit()


# Ensure tables exist regardless of startup method (`python app.py` or `flask run`).
init_db()


def app_version() -> str:
    return VERSION_PATH.read_text(encoding="utf-8").strip()


def normalize_username(username: str) -> str:
    return username.strip().lower()


def chess_com_headers() -> dict[str, str]:
    return {"User-Agent": "chessedu-local-viewer/1.0"}


def score_from_result(result: str) -> float:
    win_results = {"win"}
    draw_results = {
        "agreed",
        "repetition",
        "stalemate",
        "timevsinsufficient",
        "insufficient",
        "50move",
    }
    if result in win_results:
        return 1.0
    if result in draw_results:
        return 0.5
    return 0.0


def fetch_archives(username: str) -> list[str]:
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    response = requests.get(url, headers=chess_com_headers(), timeout=CHESS_COM_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return data.get("archives", [])


def fetch_monthly_games(archive_url: str) -> list[dict[str, Any]]:
    response = requests.get(archive_url, headers=chess_com_headers(), timeout=CHESS_COM_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return data.get("games", [])


def game_id_from_payload(game: dict[str, Any]) -> str | None:
    return game.get("uuid") or game.get("url")


def parse_game_and_index(game_id: str, pgn_text: str) -> list[tuple[int, str, str, str, str, str]]:
    parsed_game = chess.pgn.read_game(io.StringIO(pgn_text))
    if parsed_game is None:
        return []

    board = parsed_game.board()
    positions: list[tuple[int, str, str, str, str, str]] = []

    ply = 1
    for move in parsed_game.mainline_moves():
        fen_before = board.fen()
        san = board.san(move)
        uci = move.uci()
        side_to_move = "w" if board.turn == chess.WHITE else "b"
        board.push(move)
        next_fen = board.fen()
        positions.append((ply, fen_before, san, uci, next_fen, side_to_move))
        ply += 1

    return positions


def pgn_headers(pgn_text: str) -> dict[str, str]:
    parsed_game = chess.pgn.read_game(io.StringIO(pgn_text))
    if parsed_game is None:
        return {}
    return dict(parsed_game.headers)


def upsert_game(conn: sqlite3.Connection, game: dict[str, Any]) -> bool:
    game_id = game_id_from_payload(game)
    pgn = game.get("pgn")
    white = (game.get("white") or {}).get("username")
    black = (game.get("black") or {}).get("username")

    if not game_id or not pgn or not white or not black:
        return False

    white_result = (game.get("white") or {}).get("result", "")
    black_result = (game.get("black") or {}).get("result", "")

    now = int(time.time())
    conn.execute(
        """
        INSERT INTO games (
            id, url, end_time, white, black,
            white_result, black_result,
            white_score, black_score,
            time_class, rules, pgn, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            url=excluded.url,
            end_time=excluded.end_time,
            white=excluded.white,
            black=excluded.black,
            white_result=excluded.white_result,
            black_result=excluded.black_result,
            white_score=excluded.white_score,
            black_score=excluded.black_score,
            time_class=excluded.time_class,
            rules=excluded.rules,
            pgn=excluded.pgn,
            imported_at=excluded.imported_at
        """,
        (
            game_id,
            game.get("url"),
            game.get("end_time"),
            normalize_username(white),
            normalize_username(black),
            white_result,
            black_result,
            score_from_result(white_result),
            score_from_result(black_result),
            game.get("time_class"),
            game.get("rules"),
            pgn,
            now,
        ),
    )

    conn.execute("DELETE FROM positions WHERE game_id = ?", (game_id,))
    indexed_positions = parse_game_and_index(game_id, pgn)
    if indexed_positions:
        conn.executemany(
            """
            INSERT INTO positions (game_id, ply, fen, move_san, move_uci, next_fen, side_to_move)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [(game_id, *position) for position in indexed_positions],
        )

    return True


def save_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def infer_username_from_games(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        """
        WITH players AS (
            SELECT white AS username FROM games
            UNION ALL
            SELECT black AS username FROM games
        )
        SELECT username, COUNT(*) AS n
        FROM players
        WHERE username IS NOT NULL AND TRIM(username) <> ''
        GROUP BY username
        ORDER BY n DESC, username ASC
        LIMIT 1
        """
    ).fetchone()
    return row["username"] if row else None


def parse_elo_header(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if not raw.isdigit():
        return None
    return int(raw)


def fen_from_move_list(moves_uci: list[str]) -> str:
    board = chess.Board()
    for uci in moves_uci:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError(f"Lance ilegal na sequência: {uci}")
        board.push(move)
    return board.fen()


def validate_color_filter(value: str) -> str:
    color = (value or "any").strip().lower()
    if color not in {"any", "white", "black"}:
        raise ValueError("Parâmetro color inválido. Use: any, white, black.")
    return color


def parse_time_classes(value: str | None) -> list[str]:
    allowed = {"blitz", "rapid", "bullet", "outros"}
    if value is None:
        return ["blitz", "rapid", "bullet", "outros"]

    parsed = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not parsed:
        raise ValueError("Parâmetro time_classes inválido. Informe ao menos um ritmo.")
    if any(item not in allowed for item in parsed):
        raise ValueError("Parâmetro time_classes inválido. Use: blitz, rapid, bullet, outros.")

    deduped: list[str] = []
    for item in parsed:
        if item not in deduped:
            deduped.append(item)
    return deduped


def parse_bool_flag(value: str | None) -> bool:
    normalized = (value or "0").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def build_game_filters_sql(
    username: str, color_filter: str, time_classes: list[str], ignore_timeout_losses: bool
) -> tuple[str, list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if color_filter == "white":
        conditions.append("g.white = ?")
        params.append(username)
    elif color_filter == "black":
        conditions.append("g.black = ?")
        params.append(username)

    main_time_classes = [item for item in time_classes if item in {"blitz", "rapid", "bullet"}]
    include_others = "outros" in time_classes

    if main_time_classes and include_others:
        placeholders = ",".join(["?"] * len(main_time_classes))
        conditions.append(
            f"(g.time_class IN ({placeholders}) OR g.time_class IS NULL OR g.time_class NOT IN ('blitz', 'rapid', 'bullet'))"
        )
        params.extend(main_time_classes)
    elif main_time_classes:
        placeholders = ",".join(["?"] * len(main_time_classes))
        conditions.append(f"g.time_class IN ({placeholders})")
        params.extend(main_time_classes)
    else:
        conditions.append("(g.time_class IS NULL OR g.time_class NOT IN ('blitz', 'rapid', 'bullet'))")

    if ignore_timeout_losses:
        conditions.append("NOT (g.white_result = 'timeout' OR g.black_result = 'timeout')")

    if not conditions:
        return "", params

    return " AND " + " AND ".join(conditions), params


def result_label(white_result: str | None, black_result: str | None) -> str:
    white = (white_result or "").strip().lower()
    black = (black_result or "").strip().lower()

    draw_tags = {"agreed", "repetition", "stalemate", "timevsinsufficient", "insufficient", "50move"}
    white_loses = {"resigned", "timeout", "checkmated", "abandoned", "lose"}
    black_loses = {"resigned", "timeout", "checkmated", "abandoned", "lose"}

    if white == "win":
        score = "1-0"
    elif black == "win":
        score = "0-1"
    elif white in draw_tags or black in draw_tags:
        score = "1/2-1/2"
    elif white in white_loses:
        score = "0-1"
    elif black in black_loses:
        score = "1-0"
    else:
        score = "1/2-1/2"

    if "repetition" in {white, black}:
        reason = "repetition"
    elif "50move" in {white, black}:
        reason = "50-move"
    elif "stalemate" in {white, black}:
        reason = "stalemate"
    elif "timeout" in {white, black} or "timevsinsufficient" in {white, black}:
        reason = "time"
    else:
        reason = "resigned"

    return f"{score} ({reason})"


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    with closing(db_conn()) as conn:
        username = get_setting(conn, "username")
        game_count = conn.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"]
        if game_count > 0 and not username:
            inferred = infer_username_from_games(conn)
            if inferred:
                username = inferred
                save_setting(conn, "username", inferred)
                conn.commit()
    return jsonify(
        {
            "username": username,
            "game_count": game_count,
            "start_fen": chess.Board().fen(),
            "version": app_version(),
        }
    )


@app.post("/api/sync")
def api_sync():
    payload = request.get_json(silent=True) or {}
    username_input = payload.get("username", "").strip()

    if not username_input:
        return jsonify({"error": "Informe seu username do Chess.com."}), 400

    username = normalize_username(username_input)

    try:
        archives = fetch_archives(username)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        return jsonify({"error": f"Falha ao buscar arquivos de partidas: HTTP {status}"}), 502
    except requests.RequestException as exc:
        return jsonify({"error": f"Falha de conexão com Chess.com: {exc}"}), 502

    synced_archives = 0
    imported_games = 0

    total_games_in_db = 0
    with closing(db_conn()) as conn:
        already_synced = {
            row["archive_url"]
            for row in conn.execute("SELECT archive_url FROM archives").fetchall()
        }

        for archive_url in archives:
            if archive_url in already_synced:
                continue

            try:
                monthly_games = fetch_monthly_games(archive_url)
            except requests.RequestException:
                continue

            for game in monthly_games:
                if upsert_game(conn, game):
                    imported_games += 1

            conn.execute(
                "INSERT OR REPLACE INTO archives(archive_url, synced_at) VALUES (?, ?)",
                (archive_url, int(time.time())),
            )
            synced_archives += 1

        save_setting(conn, "username", username)
        total_games_in_db = conn.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"]
        conn.commit()

    return jsonify(
        {
            "username": username,
            "archives_total": len(archives),
            "archives_synced_now": synced_archives,
            "games_imported_now": imported_games,
            "games_total_in_db": total_games_in_db,
        }
    )


@app.get("/api/stats")
def api_stats():
    username = request.args.get("username", "").strip().lower()
    fen = request.args.get("fen", "").strip()
    color = request.args.get("color", "any")
    time_classes = request.args.get("time_classes")
    ignore_timeout_losses = request.args.get("ignore_timeout_losses", "0")

    if not username or not fen:
        return jsonify({"error": "Parâmetros obrigatórios: username e fen."}), 400
    try:
        color_filter = validate_color_filter(color)
        selected_time_classes = parse_time_classes(time_classes)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    filters_sql, filter_params = build_game_filters_sql(
        username=username,
        color_filter=color_filter,
        time_classes=selected_time_classes,
        ignore_timeout_losses=parse_bool_flag(ignore_timeout_losses),
    )

    query = f"""
            SELECT
                p.move_san,
                p.move_uci,
                COUNT(*) AS games_count,
                AVG(
                    CASE
                        WHEN g.white = ? THEN g.white_score
                        WHEN g.black = ? THEN g.black_score
                    END
                ) AS win_rate
            FROM positions p
            JOIN games g ON g.id = p.game_id
            WHERE p.fen = ?
              AND (g.white = ? OR g.black = ?)
              {filters_sql}
            GROUP BY p.move_san, p.move_uci
            ORDER BY games_count DESC, win_rate DESC
            """
    params = [username, username, fen, username, username]
    params.extend(filter_params)

    with closing(db_conn()) as conn:
        rows = conn.execute(query, params).fetchall()

    stats = [
        {
            "san": row["move_san"],
            "uci": row["move_uci"],
            "games": row["games_count"],
            "win_rate": round(float(row["win_rate"] or 0.0) * 100.0, 1),
        }
        for row in rows
    ]
    return jsonify({"fen": fen, "moves": stats})


@app.get("/api/games")
def api_games():
    username = request.args.get("username", "").strip().lower()
    fen = request.args.get("fen", "").strip()
    color = request.args.get("color", "any")
    time_classes = request.args.get("time_classes")
    ignore_timeout_losses = request.args.get("ignore_timeout_losses", "0")

    if not username or not fen:
        return jsonify({"error": "Parâmetros obrigatórios: username e fen."}), 400
    try:
        color_filter = validate_color_filter(color)
        selected_time_classes = parse_time_classes(time_classes)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    filters_sql, filter_params = build_game_filters_sql(
        username=username,
        color_filter=color_filter,
        time_classes=selected_time_classes,
        ignore_timeout_losses=parse_bool_flag(ignore_timeout_losses),
    )

    query = f"""
            SELECT DISTINCT
                g.id,
                g.url,
                g.end_time,
                g.white,
                g.black,
                g.white_result,
                g.black_result,
                g.time_class
            FROM positions p
            JOIN games g ON g.id = p.game_id
            WHERE p.fen = ?
              AND (g.white = ? OR g.black = ?)
              {filters_sql}
            ORDER BY g.end_time DESC
            LIMIT 250
            """
    params = [fen, username, username]
    params.extend(filter_params)

    with closing(db_conn()) as conn:
        rows = conn.execute(query, params).fetchall()

    games = []
    for row in rows:
        is_white = row["white"] == username
        my_result = row["white_result"] if is_white else row["black_result"]
        games.append(
            {
                "id": row["id"],
                "url": row["url"],
                "end_time": row["end_time"],
                "white": row["white"],
                "black": row["black"],
                "time_class": row["time_class"],
                "my_result": my_result,
                "result_label": result_label(row["white_result"], row["black_result"]),
            }
        )

    return jsonify({"fen": fen, "games": games})


@app.get("/api/count")
def api_count():
    username = request.args.get("username", "").strip().lower()
    color = request.args.get("color", "any")
    time_classes = request.args.get("time_classes")
    ignore_timeout_losses = request.args.get("ignore_timeout_losses", "0")

    if not username:
        return jsonify({"error": "Parâmetro obrigatório: username."}), 400
    try:
        color_filter = validate_color_filter(color)
        selected_time_classes = parse_time_classes(time_classes)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    filters_sql, filter_params = build_game_filters_sql(
        username=username,
        color_filter=color_filter,
        time_classes=selected_time_classes,
        ignore_timeout_losses=parse_bool_flag(ignore_timeout_losses),
    )

    query = f"""
            SELECT COUNT(*) AS n
            FROM games g
            WHERE (g.white = ? OR g.black = ?)
              {filters_sql}
            """
    params = [username, username]
    params.extend(filter_params)

    with closing(db_conn()) as conn:
        count = conn.execute(query, params).fetchone()["n"]
        has_problem_positions = table_exists(conn, "problem_positions")
        problems_count = 0
        if has_problem_positions:
            problems_query = f"""
                    SELECT COUNT(*) AS n
                    FROM problem_positions pp
                    JOIN games g ON g.id = pp.game_id
                    WHERE (g.white = ? OR g.black = ?)
                      {filters_sql}
                    """
            problems_count = conn.execute(problems_query, params).fetchone()["n"]

    return jsonify({"username": username, "count": count, "problems_count": problems_count})


@app.get("/api/problems")
def api_problems():
    username = request.args.get("username", "").strip().lower()
    color = request.args.get("color", "any")
    time_classes = request.args.get("time_classes")
    ignore_timeout_losses = request.args.get("ignore_timeout_losses", "0")

    if not username:
        return jsonify({"error": "Parâmetro obrigatório: username."}), 400
    try:
        color_filter = validate_color_filter(color)
        selected_time_classes = parse_time_classes(time_classes)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    filters_sql, filter_params = build_game_filters_sql(
        username=username,
        color_filter=color_filter,
        time_classes=selected_time_classes,
        ignore_timeout_losses=parse_bool_flag(ignore_timeout_losses),
    )
    params = [username, username]
    params.extend(filter_params)

    with closing(db_conn()) as conn:
        if not table_exists(conn, "problem_positions"):
            return jsonify({"username": username, "total": 0, "problems": []})

        query = f"""
                SELECT
                    pp.id AS problem_id,
                    pp.game_id,
                    pp.fen,
                    pp.side_to_move,
                    pp.pv_move_uci,
                    pp.pv_line_uci,
                    pp.pv_line_san,
                    pp.eval_pv_final,
                    pp.eval_prev,
                    pp.eval_curr,
                    g.white,
                    g.black,
                    g.end_time,
                    g.time_class,
                    g.pgn
                FROM problem_positions pp
                JOIN games g ON g.id = pp.game_id
                WHERE (g.white = ? OR g.black = ?)
                  {filters_sql}
                ORDER BY g.end_time DESC, pp.id DESC
                """
        rows = conn.execute(query, params).fetchall()

    problems: list[dict[str, Any]] = []
    for row in rows:
        headers = pgn_headers(row["pgn"] or "")
        problems.append(
            {
                "problem_id": row["problem_id"],
                "game_id": row["game_id"],
                "fen": row["fen"],
                "side_to_move": row["side_to_move"],
                "pv_move_uci": row["pv_move_uci"],
                "pv_line_uci": row["pv_line_uci"],
                "pv_line_san": row["pv_line_san"],
                "eval_pv_final": row["eval_pv_final"],
                "eval_prev": row["eval_prev"],
                "eval_curr": row["eval_curr"],
                "white": row["white"],
                "black": row["black"],
                "white_rating": parse_elo_header(headers.get("WhiteElo")),
                "black_rating": parse_elo_header(headers.get("BlackElo")),
                "end_time": row["end_time"],
                "time_class": row["time_class"],
            }
        )

    return jsonify({"username": username, "total": len(problems), "problems": problems})


@app.delete("/api/problems/<int:problem_id>")
def api_delete_problem(problem_id: int):
    with closing(db_conn()) as conn:
        if not table_exists(conn, "problem_positions"):
            return jsonify({"error": "Tabela de problemas não encontrada."}), 404

        row = conn.execute(
            """
            SELECT id, game_id
            FROM problem_positions
            WHERE id = ?
            """,
            (problem_id,),
        ).fetchone()
        if row is None:
            return jsonify({"error": "Problema não encontrado."}), 404

        conn.execute("DELETE FROM problem_positions WHERE id = ?", (problem_id,))
        conn.commit()

    return jsonify({"ok": True, "problem_id": problem_id, "game_id": row["game_id"]})


@app.get("/api/game/<game_id>")
def api_game(game_id: str):
    with closing(db_conn()) as conn:
        row = conn.execute(
            """
            SELECT id, url, white, black, end_time, pgn, time_class, white_result, black_result
            FROM games WHERE id = ?
            """,
            (game_id,),
        ).fetchone()

    if not row:
        return jsonify({"error": "Partida não encontrada."}), 404

    headers = pgn_headers(row["pgn"])
    return jsonify(
        {
            "id": row["id"],
            "url": row["url"],
            "white": row["white"],
            "black": row["black"],
            "white_rating": headers.get("WhiteElo"),
            "black_rating": headers.get("BlackElo"),
            "end_time": row["end_time"],
            "time_class": row["time_class"],
            "white_result": row["white_result"],
            "black_result": row["black_result"],
            "result_label": result_label(row["white_result"], row["black_result"]),
            "pgn": row["pgn"],
        }
    )


@app.post("/api/fen")
def api_fen_from_moves():
    payload = request.get_json(silent=True) or {}
    moves = payload.get("moves", [])

    if not isinstance(moves, list):
        return jsonify({"error": "moves precisa ser uma lista de lances UCI."}), 400

    try:
        fen = fen_from_move_list(moves)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"fen": fen})


if __name__ == "__main__":  # pragma: no cover
    init_db()
    app.run(debug=True)
