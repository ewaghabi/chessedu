/* global Chess, Chessboard, $ */

const game = new Chess();
let board = null;
let username = "";
let currentMoves = [];

const el = {
  username: document.getElementById("username"),
  syncBtn: document.getElementById("sync-btn"),
  resetBtn: document.getElementById("reset-btn"),
  backBtn: document.getElementById("back-btn"),
  gamesBtn: document.getElementById("games-btn"),
  dbCount: document.getElementById("db-count"),
  appVersion: document.getElementById("app-version"),
  status: document.getElementById("status"),
  movesList: document.getElementById("moves-list"),
  gamesList: document.getElementById("games-list"),
  positionInfo: document.getElementById("position-info"),
};

function setStatus(text, mode = "info") {
  el.status.textContent = text;
  if (mode === "error") {
    el.status.className = "warning";
    return;
  }
  if (mode === "loading") {
    el.status.className = "loading";
    return;
  }
  el.status.className = "";
}

function updateDbCount(count) {
  el.dbCount.textContent = `Banco: ${count} partidas`;
}

function updateVersion(version) {
  if (!version) return;
  el.appVersion.textContent = `v${version}`;
}

function setPositionInfo() {
  const side = game.turn() === "w" ? "Brancas" : "Pretas";
  el.positionInfo.textContent = `Ply: ${currentMoves.length} | Vez: ${side}`;
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

async function loadState() {
  const data = await apiJson("/api/state");
  if (data.username) {
    username = data.username;
    el.username.value = data.username;
  }
  updateVersion(data.version);
  updateDbCount(data.game_count || 0);
  setStatus(`Pronto. Banco local: ${data.game_count} partidas.`);
}

function resetBoard() {
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
    item.className = "item";

    const left = document.createElement("div");
    left.className = "left";

    const title = document.createElement("div");
    title.className = "title";
    title.textContent = m.san;

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${m.games} partidas | ${m.win_rate}% vitórias`;

    left.appendChild(title);
    left.appendChild(meta);

    const btn = document.createElement("button");
    btn.textContent = "Entrar";
    btn.addEventListener("click", () => {
      const move = game.move(m.uci, { sloppy: true });
      if (!move) return;
      currentMoves.push(m.uci);
      board.position(game.fen());
      refreshFromPosition();
    });

    item.appendChild(left);
    item.appendChild(btn);
    el.movesList.appendChild(item);
  }
}

function formatDateFromUnix(ts) {
  if (!ts) return "Data desconhecida";
  return new Date(ts * 1000).toLocaleString();
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
    meta.textContent = `${formatDateFromUnix(g.end_time)} | ${g.time_class || "?"} | resultado: ${g.my_result || "?"}`;

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
  try {
    const data = await apiJson(`/api/game/${encodeURIComponent(gameId)}`);
    const replay = new Chess();
    const parsed = replay.load_pgn(data.pgn);
    if (!parsed) {
      throw new Error("Não foi possível carregar PGN da partida.");
    }

    resetBoard();
    const history = replay.history({ verbose: true });
    for (const mv of history) {
      game.move(mv.san, { sloppy: true });
      currentMoves.push(mv.from + mv.to + (mv.promotion || ""));
    }

    board.position(game.fen());
    await refreshFromPosition();
    setStatus(`Partida carregada: ${data.white} vs ${data.black}`);
  } catch (err) {
    setStatus(err.message, "error");
  }
}

async function refreshFromPosition(loadGames = false) {
  if (!username) {
    setStatus("Informe o usuário e sincronize ao menos uma vez.", "error");
    return;
  }

  setPositionInfo();

  try {
    const fen = await getCurrentFen();
    const statsData = await apiJson(
      `/api/stats?username=${encodeURIComponent(username)}&fen=${encodeURIComponent(fen)}`
    );
    renderMoves(statsData.moves);

    if (loadGames) {
      const gamesData = await apiJson(
        `/api/games?username=${encodeURIComponent(username)}&fen=${encodeURIComponent(fen)}`
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
  el.syncBtn.disabled = true;

  try {
    const data = await apiJson("/api/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: u }),
    });

    username = data.username;
    updateDbCount(data.games_total_in_db || 0);
    setStatus(
      `Sync concluído. Arquivos novos: ${data.archives_synced_now}/${data.archives_total}. Partidas processadas agora: ${data.games_imported_now}. Total no banco: ${data.games_total_in_db}.`
    );
    await loadState();
    await refreshFromPosition(true);
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    el.syncBtn.disabled = false;
  }
}

function wireEvents() {
  el.syncBtn.addEventListener("click", doSync);
  el.resetBtn.addEventListener("click", async () => {
    resetBoard();
    await refreshFromPosition();
  });

  el.backBtn.addEventListener("click", async () => {
    if (!currentMoves.length) return;
    game.undo();
    currentMoves.pop();
    board.position(game.fen());
    await refreshFromPosition();
  });

  el.gamesBtn.addEventListener("click", async () => {
    await refreshFromPosition(true);
  });
}

async function main() {
  setStatus("Inicializando interface...", "loading");
  try {
    board = Chessboard("board", {
      position: "start",
      draggable: false,
    });

    wireEvents();
    setPositionInfo();
    await loadState();
    await refreshFromPosition();
  } catch (err) {
    setStatus(`Falha ao inicializar app: ${err.message}`, "error");
  }
}

main();
