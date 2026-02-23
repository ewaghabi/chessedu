/* global Chess, Chessboard */

let game = null;
let board = null;
let username = "";
let currentMoves = [];
let colorFilter = "any";
let loadedGameMoves = null;
let replayIndex = 0;

const el = {
  username: document.getElementById("username"),
  syncBtn: document.getElementById("sync-btn"),
  resetBtn: document.getElementById("reset-btn"),
  backBtn: document.getElementById("back-btn"),
  replayFirst: document.getElementById("replay-first"),
  replayPrev: document.getElementById("replay-prev"),
  replayNext: document.getElementById("replay-next"),
  replayLast: document.getElementById("replay-last"),
  colorFilter: document.getElementById("color-filter"),
  dbCount: document.getElementById("db-count"),
  appVersion: document.getElementById("app-version"),
  status: document.getElementById("status"),
  movesList: document.getElementById("moves-list"),
  gamesList: document.getElementById("games-list"),
  positionInfo: document.getElementById("position-info"),
  gameMeta: document.getElementById("game-meta"),
  playerTop: document.getElementById("player-top"),
  playerBottom: document.getElementById("player-bottom"),
};

function setStatus(text, mode = "info") {
  el.status.textContent = text;
  el.status.className = `status-message ${mode}`;
}

function setSyncLoading(isLoading) {
  el.syncBtn.disabled = isLoading;
  el.syncBtn.classList.toggle("is-loading", isLoading);
}

function updateDbCount(count) {
  el.dbCount.textContent = `Banco: ${count} partidas`;
}

function updateVersion(version) {
  if (!version) return;
  el.appVersion.textContent = `v${version}`;
}

function setPositionInfo() {
  if (!game) {
    el.positionInfo.textContent = `Ply: ${currentMoves.length} | Vez: -`;
    return;
  }
  const side = game.turn() === "w" ? "Brancas" : "Pretas";
  el.positionInfo.textContent = `Ply: ${currentMoves.length} | Vez: ${side}`;
}

function updateReplayButtons() {
  const hasLoadedGame = Array.isArray(loadedGameMoves) && loadedGameMoves.length > 0;
  el.replayFirst.disabled = !hasLoadedGame || replayIndex <= 0;
  el.replayPrev.disabled = !hasLoadedGame || replayIndex <= 0;
  el.replayNext.disabled = !hasLoadedGame || replayIndex >= loadedGameMoves.length;
  el.replayLast.disabled = !hasLoadedGame || replayIndex >= loadedGameMoves.length;
}

function clearReplayState() {
  loadedGameMoves = null;
  replayIndex = 0;
  updateReplayButtons();
  el.gameMeta.textContent = "";
  el.playerTop.textContent = "-";
  el.playerBottom.textContent = "-";
}

function renderReplayPosition() {
  if (!game || !board || !Array.isArray(loadedGameMoves)) return;

  game.reset();
  for (let i = 0; i < replayIndex; i += 1) {
    game.move(loadedGameMoves[i], { sloppy: true });
  }
  board.position(game.fen());
  setPositionInfo();
  updateReplayButtons();
}

async function apiJson(url, options = {}) {
  const resp = await fetch(url, options);
  const raw = await resp.text();
  let data = {};
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch (_) {
    data = { error: raw || "Resposta inválida da API." };
  }
  if (!resp.ok) {
    throw new Error(data.error || "Erro inesperado na API.");
  }
  return data;
}

async function loadState(updateStatus = true) {
  const data = await apiJson("/api/state");
  if (data.username) {
    username = data.username;
    el.username.value = data.username;
  }
  el.username.disabled = (data.game_count || 0) > 0;
  updateVersion(data.version);
  updateDbCount(data.game_count || 0);
  if (updateStatus) {
    setStatus(`Pronto. Banco local: ${data.game_count} partidas.`, "success");
  }
}

function resetBoard() {
  if (!game || !board) return;
  clearReplayState();
  game.reset();
  currentMoves = [];
  board.position(game.fen());
  setPositionInfo();
}

async function getCurrentFen() {
  const payload = await apiJson("/api/fen", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ moves: currentMoves }),
  });
  return payload.fen;
}

function renderMoves(moves) {
  el.movesList.innerHTML = "";
  if (!moves.length) {
    el.movesList.innerHTML = '<div class="item"><span>Sem próximos lances para essa posição.</span></div>';
    return;
  }

  for (const m of moves) {
    const item = document.createElement("div");
    item.className = "item move-item";
    item.setAttribute("role", "button");
    item.setAttribute("tabindex", "0");

    const moveMain = document.createElement("div");
    moveMain.className = "move-main";
    moveMain.textContent = m.san;

    const moveStats = document.createElement("div");
    moveStats.className = "move-stats";
    moveStats.textContent = `${m.win_rate}%`;

    const gamesCount = document.createElement("span");
    gamesCount.className = "move-games";
    gamesCount.textContent = `(${m.games})`;
    moveStats.appendChild(gamesCount);

    const goToMove = async () => {
      const move = game.move(m.uci, { sloppy: true });
      if (!move) return;
      currentMoves.push(m.uci);
      board.position(game.fen());
      await refreshFromPosition(true);
    };
    item.addEventListener("click", goToMove);
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        goToMove();
      }
    });

    item.appendChild(moveMain);
    item.appendChild(moveStats);
    el.movesList.appendChild(item);
  }
}

function formatDateFromUnix(ts) {
  if (!ts) return "Data desconhecida";
  return new Date(ts * 1000).toLocaleString();
}

function buildPlayerLabel(name, rating) {
  if (!name) return "-";
  return rating ? `${name} (${rating})` : name;
}

function renderGames(games) {
  el.gamesList.innerHTML = "";
  if (!games.length) {
    el.gamesList.innerHTML = '<div class="item"><span>Nenhuma partida encontrada para essa posição.</span></div>';
    return;
  }

  for (const g of games) {
    const item = document.createElement("div");
    item.className = "item";

    const left = document.createElement("div");
    left.className = "left";

    const title = document.createElement("div");
    title.className = "title";
    title.textContent = `${g.white} vs ${g.black}`;

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${formatDateFromUnix(g.end_time)} | ${g.time_class || "?"} | resultado: ${g.result_label || g.my_result || "?"}`;

    left.appendChild(title);
    left.appendChild(meta);

    const btn = document.createElement("button");
    btn.textContent = "Carregar";
    btn.addEventListener("click", () => loadGame(g.id));

    item.appendChild(left);
    item.appendChild(btn);
    el.gamesList.appendChild(item);
  }
}

async function loadGame(gameId) {
  if (!game || !board) {
    setStatus("Tabuleiro indisponível no momento.", "error");
    return;
  }

  try {
    const data = await apiJson(`/api/game/${encodeURIComponent(gameId)}`);
    const replay = new Chess();
    const parsed = replay.load_pgn(data.pgn);
    if (!parsed) {
      throw new Error("Não foi possível carregar PGN da partida.");
    }

    resetBoard();
    const history = replay.history({ verbose: true });
    loadedGameMoves = [];
    for (const mv of history) {
      const uci = mv.from + mv.to + (mv.promotion || "");
      loadedGameMoves.push(uci);
      game.move(mv.san, { sloppy: true });
    }

    replayIndex = loadedGameMoves.length;
    board.position(game.fen());
    el.playerTop.textContent = buildPlayerLabel(data.black, data.black_rating);
    el.playerBottom.textContent = buildPlayerLabel(data.white, data.white_rating);
    const metaDate = formatDateFromUnix(data.end_time);
    const metaTimeClass = data.time_class || "?";
    const metaResult = data.result_label || "?";
    el.gameMeta.textContent = `${metaDate} | ${metaTimeClass} | ${metaResult}`;
    setPositionInfo();
    updateReplayButtons();
    setStatus(`Partida carregada: ${data.white} vs ${data.black}`, "success");
  } catch (err) {
    setStatus(err.message, "error");
  }
}

async function refreshFromPosition(loadGames = false) {
  if (!game || !board) {
    setStatus("Tabuleiro indisponível no momento.", "error");
    return;
  }

  if (!username) {
    setStatus("Informe o usuário e sincronize ao menos uma vez.", "error");
    return;
  }

  setPositionInfo();

  try {
    const fen = await getCurrentFen();
    board.position(fen);
    const statsData = await apiJson(
      `/api/stats?username=${encodeURIComponent(username)}&fen=${encodeURIComponent(fen)}&color=${encodeURIComponent(colorFilter)}`
    );
    renderMoves(statsData.moves);

    if (loadGames) {
      const gamesData = await apiJson(
        `/api/games?username=${encodeURIComponent(username)}&fen=${encodeURIComponent(fen)}&color=${encodeURIComponent(colorFilter)}`
      );
      renderGames(gamesData.games);
    }
  } catch (err) {
    setStatus(err.message, "error");
  }
}

async function doSync() {
  const u = el.username.value.trim().toLowerCase();
  if (!u) {
    setStatus("Informe seu usuário do Chess.com.", "error");
    return;
  }

  setStatus("Sincronizando partidas... aguarde.", "loading");
  setSyncLoading(true);

  try {
    const data = await apiJson("/api/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: u }),
    });

    username = data.username;
    updateDbCount(data.games_total_in_db || 0);
    setStatus(
      `Sync concluído. Arquivos novos: ${data.archives_synced_now}/${data.archives_total}. Partidas processadas agora: ${data.games_imported_now}. Total no banco: ${data.games_total_in_db}.`,
      "success"
    );
    await loadState(false);
    if (game && board) {
      await refreshFromPosition(true);
    }
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    setSyncLoading(false);
  }
}

function wireEvents() {
  el.syncBtn.addEventListener("click", doSync);
  el.resetBtn.addEventListener("click", async () => {
    if (!game || !board) return;
    resetBoard();
    await refreshFromPosition();
  });

  el.backBtn.addEventListener("click", async () => {
    if (!game || !board) return;
    if (!currentMoves.length) return;
    game.undo();
    currentMoves.pop();
    board.position(game.fen());
    await refreshFromPosition();
  });

  el.colorFilter.addEventListener("change", async () => {
    colorFilter = el.colorFilter.value;
    await refreshFromPosition(true);
  });

  el.replayFirst.addEventListener("click", () => {
    if (!loadedGameMoves) return;
    replayIndex = 0;
    renderReplayPosition();
  });

  el.replayPrev.addEventListener("click", () => {
    if (!loadedGameMoves || replayIndex <= 0) return;
    replayIndex -= 1;
    renderReplayPosition();
  });

  el.replayNext.addEventListener("click", () => {
    if (!loadedGameMoves || replayIndex >= loadedGameMoves.length) return;
    replayIndex += 1;
    renderReplayPosition();
  });

  el.replayLast.addEventListener("click", () => {
    if (!loadedGameMoves) return;
    replayIndex = loadedGameMoves.length;
    renderReplayPosition();
  });
}

async function main() {
  setStatus("Inicializando interface...", "loading");
  wireEvents();
  setPositionInfo();

  window.addEventListener("error", (event) => {
    const msg = event.error?.message || event.message || "Erro inesperado no frontend.";
    setStatus(`Erro no frontend: ${msg}`, "error");
  });

  window.addEventListener("unhandledrejection", (event) => {
    const msg = event.reason?.message || String(event.reason || "Erro assíncrono no frontend.");
    setStatus(`Erro no frontend: ${msg}`, "error");
  });

  try {
    if (typeof Chess === "undefined") {
      throw new Error("Biblioteca chess.js não carregou.");
    }
    if (typeof Chessboard === "undefined") {
      throw new Error("Biblioteca chessboard.js não carregou.");
    }

    game = new Chess();
    board = Chessboard("board", {
      position: "start",
      draggable: false,
      pieceTheme: "/static/vendor/chessboardjs/img/chesspieces/wikipedia/{piece}.png",
    });

    setPositionInfo();
    updateReplayButtons();
    await loadState(true);
    await refreshFromPosition();
  } catch (err) {
    setStatus(`Falha ao inicializar app: ${err.message}`, "error");
  }
}

main();
