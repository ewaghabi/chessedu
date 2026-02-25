/* global Chess, Chessboard */

let game = null;
let board = null;
let username = "";
let currentMoves = [];
let colorFilter = "any";
let autoFlipEnabled = false;
let ignoreTimeoutLosses = false;
let selectedTimeClasses = new Set(["blitz", "rapid", "bullet", "outros"]);
let loadedGameMoves = null;
let replayIndex = 0;
let loadedGameIsUserBlack = false;
let problemBoard = null;
let problemGame = null;
let problemSession = {
  problems: [],
  queue: [],
  queuePos: 0,
  current: null,
  timerId: null,
  startedAtMs: 0,
  locked: true,
  debugHoldActive: false,
  debugRestore: null,
};
let problemDragPieceCode = null;

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
  colorFilterLabel: document.getElementById("color-filter-label"),
  autoFlip: document.getElementById("auto-flip"),
  timeBlitz: document.getElementById("time-blitz"),
  timeRapid: document.getElementById("time-rapid"),
  timeBullet: document.getElementById("time-bullet"),
  timeOutros: document.getElementById("time-outros"),
  ignoreTimeoutLosses: document.getElementById("ignore-timeout-losses"),
  filteredCount: document.getElementById("filtered-count"),
  filteredGamesCount: document.getElementById("filtered-games-count"),
  filteredProblemsCount: document.getElementById("filtered-problems-count"),
  goProblemsBtn: document.getElementById("go-problems-btn"),
  dbCount: document.getElementById("db-count"),
  appVersion: document.getElementById("app-version"),
  status: document.getElementById("status"),
  movesList: document.getElementById("moves-list"),
  gamesList: document.getElementById("games-list"),
  gameMeta: document.getElementById("game-meta"),
  playerTop: document.getElementById("player-top"),
  playerBottom: document.getElementById("player-bottom"),
  problemModalOverlay: document.getElementById("problem-modal-overlay"),
  problemModalClose: document.getElementById("problem-modal-close"),
  problemModalMeta: document.getElementById("problem-modal-meta"),
  problemPlayerTop: document.getElementById("problem-player-top"),
  problemPlayerBottom: document.getElementById("problem-player-bottom"),
  problemTimer: document.getElementById("problem-timer"),
  problemFeedback: document.getElementById("problem-feedback"),
  problemEvalRow: document.getElementById("problem-eval-row"),
  problemEvalPrev: document.getElementById("problem-eval-prev"),
  problemEvalPost: document.getElementById("problem-eval-post"),
  problemNextBtn: document.getElementById("problem-next-btn"),
  problemRepeatBtn: document.getElementById("problem-repeat-btn"),
  problemShowSolutionBtn: document.getElementById("problem-show-solution-btn"),
  problemDebugHoldBtn: document.getElementById("problem-debug-hold-btn"),
  problemSkipBtn: document.getElementById("problem-skip-btn"),
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

function updateColorFilterLabel() {
  el.colorFilterLabel.textContent = username ? `${username} joga de:` : "Jogador joga de:";
}

function updateFilteredCount(count, problemsCount = 0) {
  el.filteredGamesCount.textContent = `Partidas: ${count}`;
  el.filteredProblemsCount.textContent = `Problemas: ${problemsCount}`;
  el.goProblemsBtn.disabled = !username || problemsCount <= 0;
}

function buildFilterQuery() {
  const timeClasses = [...selectedTimeClasses].join(",");
  return `color=${encodeURIComponent(colorFilter)}&time_classes=${encodeURIComponent(timeClasses)}&ignore_timeout_losses=${
    ignoreTimeoutLosses ? "1" : "0"
  }`;
}

function applyBoardOrientation() {
  if (!board) return;
  if (!autoFlipEnabled) {
    board.orientation("white");
    return;
  }
  if (loadedGameMoves && loadedGameIsUserBlack) {
    board.orientation("black");
    return;
  }
  board.orientation(colorFilter === "black" ? "black" : "white");
}

async function refreshFilteredCount() {
  if (!username) {
    updateFilteredCount(0, 0);
    return;
  }
  const data = await apiJson(`/api/count?username=${encodeURIComponent(username)}&${buildFilterQuery()}`);
  updateFilteredCount(data.count || 0, data.problems_count || 0);
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
  loadedGameIsUserBlack = false;
  updateReplayButtons();
  el.gameMeta.textContent = "";
  el.playerTop.textContent = "-";
  el.playerBottom.textContent = "-";
  applyBoardOrientation();
}

function renderReplayPosition() {
  if (!game || !board || !Array.isArray(loadedGameMoves)) return;

  game.reset();
  for (let i = 0; i < replayIndex; i += 1) {
    game.move(loadedGameMoves[i], { sloppy: true });
  }
  board.position(game.fen());
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
  updateColorFilterLabel();
  await refreshFilteredCount();
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

  const fenParts = game.fen().split(" ");
  const turn = fenParts[1];
  const fullmove = Number(fenParts[5] || 1);

  function formatMoveLabel(san, moveTurn, moveNumber) {
    if (moveTurn === "b") {
      return `${moveNumber}... ${san}`;
    }
    return `${moveNumber}. ${san}`;
  }

  for (const m of moves) {
    const item = document.createElement("div");
    item.className = "item move-item";
    item.setAttribute("role", "button");
    item.setAttribute("tabindex", "0");
    const pct = Math.max(0, Math.min(100, Number(m.win_rate) || 0));
    item.style.setProperty("--win-rate", `${pct}%`);

    const moveMain = document.createElement("div");
    moveMain.className = "move-main";
    moveMain.textContent = formatMoveLabel(m.san, turn, fullmove);

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

function shuffleArray(items) {
  const copy = items.slice();
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    const tmp = copy[i];
    copy[i] = copy[j];
    copy[j] = tmp;
  }
  return copy;
}

function formatTimerElapsed(ms) {
  const safe = Math.max(0, ms || 0);
  const tenths = Math.floor((safe % 1000) / 100);
  const totalSeconds = Math.floor(safe / 1000);
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${tenths}`;
}

function stopProblemTimer() {
  if (problemSession.timerId) {
    clearInterval(problemSession.timerId);
    problemSession.timerId = null;
  }
}

function startProblemTimer() {
  stopProblemTimer();
  problemSession.startedAtMs = Date.now();
  el.problemTimer.textContent = "00:00.0";
  problemSession.timerId = setInterval(() => {
    const elapsed = Date.now() - problemSession.startedAtMs;
    el.problemTimer.textContent = formatTimerElapsed(elapsed);
  }, 100);
}

function setProblemFeedback(text, mode = "") {
  el.problemFeedback.textContent = text;
  el.problemFeedback.className = `problem-feedback ${mode}`.trim();
}

function truncateWithEllipsis(text, maxChars = 30) {
  const value = String(text || "");
  if (value.length <= maxChars) {
    return value;
  }
  return `${value.slice(0, Math.max(0, maxChars - 3))}...`;
}

function formatSignedEval(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "?";
  }
  return `${numeric >= 0 ? "+" : ""}${numeric.toFixed(1)}`;
}

function perspectiveEval(problem, rawEval) {
  const numeric = Number(rawEval);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  return problem.side_to_move === "b" ? -numeric : numeric;
}

function buildProblemPrompt(problem) {
  const sideLabel = problem.side_to_move === "b" ? "Negras" : "Brancas";
  const prev = perspectiveEval(problem, problem.eval_prev);
  const final = perspectiveEval(problem, problem.eval_pv_final ?? problem.eval_prev);

  if (prev === null || final === null) {
    return `${sideLabel} jogam e obtêm vantagem decisiva.`;
  }

  if (final >= 2.5 && prev < 1.0) {
    if (prev <= -0.8) {
      return `${sideLabel} jogam e revertem a partida.`;
    }
    return `${sideLabel} jogam e obtêm vantagem decisiva.`;
  }

  if (Math.abs(final) <= 0.8 && prev <= -1.2) {
    return `${sideLabel} jogam e igualam a posição.`;
  }

  if (final > prev + 1.2) {
    return `${sideLabel} jogam e obtêm vantagem decisiva.`;
  }
  if (prev < 0 && final >= 0) {
    return `${sideLabel} jogam e revertem a partida.`;
  }
  return `${sideLabel} jogam e igualam a posição.`;
}

function resetProblemCursor() {
  document.body.style.cursor = "";
}

function applyProblemDragCursor(pieceCode) {
  const safeCode = (pieceCode || "").trim();
  if (!safeCode) {
    document.body.style.cursor = "grabbing";
    return;
  }
  const cursorUrl = `/static/vendor/chessboardjs/img/chesspieces/wikipedia/${safeCode}.png`;
  document.body.style.cursor = `url('${cursorUrl}') 22 22, grabbing`;
}

function setProblemEvalRowHidden(hidden) {
  el.problemEvalRow.classList.toggle("hidden", hidden);
}

function setProblemEvalDebugValues(problem) {
  const prev = formatSignedEval(problem.eval_prev);
  const post = formatSignedEval(problem.eval_pv_final ?? problem.eval_curr ?? problem.eval_prev);
  el.problemEvalPrev.textContent = `Eval anterior: ${prev}`;
  el.problemEvalPost.textContent = `Eval posterior: ${post}`;
}

function getProblemPvLine(problem) {
  return (
    (problem.pv_line_san && String(problem.pv_line_san).trim()) ||
    (problem.pv_line_uci && String(problem.pv_line_uci).trim()) ||
    (problem.pv_move_uci && String(problem.pv_move_uci).trim().toLowerCase()) ||
    "?"
  );
}

function showProblemDebugHoldInfo() {
  if (!problemSession.current || problemSession.debugHoldActive) {
    return;
  }
  problemSession.debugHoldActive = true;
  problemSession.debugRestore = {
    text: el.problemFeedback.textContent,
    className: el.problemFeedback.className,
  };
  const pvPreview = truncateWithEllipsis(getProblemPvLine(problemSession.current), 30);
  setProblemFeedback(`PV: ${pvPreview}`, "debug");
  setProblemEvalDebugValues(problemSession.current);
  setProblemEvalRowHidden(false);
}

function hideProblemDebugHoldInfo() {
  if (!problemSession.debugHoldActive) {
    return;
  }
  const restore = problemSession.debugRestore;
  if (restore) {
    el.problemFeedback.textContent = restore.text;
    el.problemFeedback.className = restore.className;
  }
  problemSession.debugRestore = null;
  problemSession.debugHoldActive = false;
  setProblemEvalRowHidden(true);
}

function buildProblemSolutionText(problem) {
  const pvLine = getProblemPvLine(problem);
  const finalEval = formatSignedEval(problem.eval_pv_final ?? problem.eval_prev ?? problem.eval_curr);
  return `PV: ${pvLine} | Eval final: ${finalEval}`;
}

function setProblemActionButtons({ showNext = false, showRepeat = false, showSolution = false } = {}) {
  el.problemNextBtn.classList.toggle("hidden", !showNext);
  el.problemRepeatBtn.classList.toggle("hidden", !showRepeat);
  el.problemShowSolutionBtn.classList.toggle("hidden", !showSolution);
}

function buildProblemQueue() {
  const indexes = problemSession.problems.map((_, idx) => idx);
  problemSession.queue = shuffleArray(indexes);
  problemSession.queuePos = 0;
}

function setProblemLabels(problem) {
  const whiteLabel = buildPlayerLabel(problem.white, problem.white_rating);
  const blackLabel = buildPlayerLabel(problem.black, problem.black_rating);
  const orientation = problem.side_to_move === "b" ? "black" : "white";

  if (orientation === "black") {
    el.problemPlayerTop.textContent = whiteLabel;
    el.problemPlayerBottom.textContent = blackLabel;
  } else {
    el.problemPlayerTop.textContent = blackLabel;
    el.problemPlayerBottom.textContent = whiteLabel;
  }

  const dateText = formatDateFromUnix(problem.end_time);
  const timeClass = problem.time_class || "?";
  el.problemModalMeta.textContent = `${problem.white} vs ${problem.black} | ${dateText} | ${timeClass}`;
}

function prepareProblemBoard(problem) {
  problemGame.load(problem.fen);
  problemBoard.orientation(problem.side_to_move === "b" ? "black" : "white");
  problemBoard.position(problem.fen);
}

function ensureProblemBoardVisible() {
  if (!problemBoard) return;
  requestAnimationFrame(() => {
    problemBoard.resize();
    if (problemGame) {
      problemBoard.position(problemGame.fen());
    }
  });
}

function showNextProblem() {
  if (!problemSession.problems.length) {
    return;
  }

  if (problemSession.queuePos >= problemSession.queue.length) {
    buildProblemQueue();
  }
  hideProblemDebugHoldInfo();

  const idx = problemSession.queue[problemSession.queuePos];
  problemSession.queuePos += 1;
  problemSession.current = problemSession.problems[idx];
  problemSession.locked = false;

  prepareProblemBoard(problemSession.current);
  ensureProblemBoardVisible();
  setProblemLabels(problemSession.current);
  setProblemFeedback(buildProblemPrompt(problemSession.current), "info");
  setProblemActionButtons({ showNext: false, showRepeat: false, showSolution: false });
  setProblemEvalRowHidden(true);
  startProblemTimer();
}

function repeatCurrentProblem() {
  if (!problemSession.current) {
    return;
  }
  hideProblemDebugHoldInfo();
  problemSession.locked = false;
  prepareProblemBoard(problemSession.current);
  ensureProblemBoardVisible();
  setProblemFeedback(buildProblemPrompt(problemSession.current), "info");
  setProblemActionButtons({ showNext: false, showRepeat: false, showSolution: false });
  setProblemEvalRowHidden(true);
  startProblemTimer();
}

function openProblemModal() {
  el.problemModalOverlay.classList.remove("hidden");
  ensureProblemBoardVisible();
}

function closeProblemModal() {
  hideProblemDebugHoldInfo();
  stopProblemTimer();
  resetProblemCursor();
  problemDragPieceCode = null;
  problemSession.current = null;
  problemSession.locked = true;
  el.problemModalOverlay.classList.add("hidden");
  setProblemFeedback("Faça o melhor lance da posição.", "info");
  setProblemActionButtons({ showNext: false, showRepeat: false, showSolution: false });
  setProblemEvalRowHidden(true);
}

async function openProblemsSession() {
  if (!username) {
    setStatus("Informe o usuário e sincronize ao menos uma vez.", "error");
    return;
  }

  const data = await apiJson(`/api/problems?username=${encodeURIComponent(username)}&${buildFilterQuery()}`);
  if (!data.total || !Array.isArray(data.problems) || !data.problems.length) {
    setStatus("Nenhum problema disponível com os filtros atuais.", "error");
    return;
  }

  problemSession.problems = data.problems;
  buildProblemQueue();
  openProblemModal();
  showNextProblem();
}

function onProblemDrop(source, target) {
  hideProblemDebugHoldInfo();
  resetProblemCursor();
  problemDragPieceCode = null;
  if (!problemSession.current || problemSession.locked) {
    return "snapback";
  }

  const attempted = problemGame.move({
    from: source,
    to: target,
    promotion: "q",
  });
  if (!attempted) {
    return "snapback";
  }

  const attemptedUci = `${attempted.from}${attempted.to}${attempted.promotion || ""}`;
  const expectedUci = (problemSession.current.pv_move_uci || "").toLowerCase();
  const isCorrect = attemptedUci.toLowerCase() === expectedUci;

  problemBoard.position(problemGame.fen());
  stopProblemTimer();
  problemSession.locked = true;

  if (isCorrect) {
    setProblemFeedback(`Correto.\n${buildProblemSolutionText(problemSession.current)}`, "success");
    setProblemActionButtons({ showNext: true, showRepeat: false, showSolution: false });
  } else {
    setProblemFeedback("Incorreto.", "error");
    setProblemActionButtons({ showNext: false, showRepeat: true, showSolution: true });
  }

  return undefined;
}

function onProblemDragStart(source, piece) {
  if (!problemSession.current || problemSession.locked) {
    return false;
  }

  const turn = problemGame.turn();
  const isWhitePiece = piece.startsWith("w");
  if ((turn === "w" && !isWhitePiece) || (turn === "b" && isWhitePiece)) {
    return false;
  }

  // Sanity check to avoid starting a drag from a square that has no legal piece.
  const squarePiece = problemGame.get(source);
  if (!squarePiece) {
    return false;
  }

  problemDragPieceCode = piece;
  applyProblemDragCursor(problemDragPieceCode);
  return true;
}

function onProblemSnapEnd() {
  resetProblemCursor();
  problemDragPieceCode = null;
  if (problemBoard && problemGame) {
    problemBoard.position(problemGame.fen());
  }
}

function renderGames(games) {
  el.gamesList.innerHTML = "";
  if (!games.length) {
    el.gamesList.innerHTML = '<div class="item"><span>Nenhuma partida encontrada para essa posição.</span></div>';
    return;
  }

  for (const g of games) {
    const item = document.createElement("div");
    item.className = "item game-result-draw";
    if (g.my_result === "win") {
      item.classList.add("game-result-win");
      item.classList.remove("game-result-draw");
    } else if (["agreed", "repetition", "stalemate", "timevsinsufficient", "insufficient", "50move"].includes(g.my_result)) {
      item.classList.add("game-result-draw");
    } else {
      item.classList.add("game-result-loss");
      item.classList.remove("game-result-draw");
    }

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
    loadedGameIsUserBlack = data.black === username;
    applyBoardOrientation();
    board.position(game.fen());
    el.playerTop.textContent = buildPlayerLabel(data.black, data.black_rating);
    el.playerBottom.textContent = buildPlayerLabel(data.white, data.white_rating);
    const metaDate = formatDateFromUnix(data.end_time);
    const metaTimeClass = data.time_class || "?";
    const metaResult = data.result_label || "?";
    el.gameMeta.textContent = `${metaDate} | ${metaTimeClass} | ${metaResult}`;
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

  try {
    const fen = await getCurrentFen();
    applyBoardOrientation();
    board.position(fen);
    const statsData = await apiJson(
      `/api/stats?username=${encodeURIComponent(username)}&fen=${encodeURIComponent(fen)}&${buildFilterQuery()}`
    );
    renderMoves(statsData.moves);

    if (loadGames) {
      const gamesData = await apiJson(
        `/api/games?username=${encodeURIComponent(username)}&fen=${encodeURIComponent(fen)}&${buildFilterQuery()}`
      );
      renderGames(gamesData.games);
    }
    await refreshFilteredCount();
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
    updateColorFilterLabel();
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
  const timeClassInputs = [
    { key: "blitz", input: el.timeBlitz },
    { key: "rapid", input: el.timeRapid },
    { key: "bullet", input: el.timeBullet },
    { key: "outros", input: el.timeOutros },
  ];

  const handleFilterChange = async () => {
    applyBoardOrientation();
    await refreshFromPosition(true);
  };

  el.goProblemsBtn.addEventListener("click", async () => {
    try {
      await openProblemsSession();
    } catch (err) {
      setStatus(err.message, "error");
    }
  });

  el.problemModalClose.addEventListener("click", closeProblemModal);
  el.problemModalOverlay.addEventListener("click", (event) => {
    if (event.target === el.problemModalOverlay) {
      closeProblemModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !el.problemModalOverlay.classList.contains("hidden")) {
      closeProblemModal();
    }
  });
  el.problemNextBtn.addEventListener("click", showNextProblem);
  el.problemRepeatBtn.addEventListener("click", repeatCurrentProblem);
  el.problemShowSolutionBtn.addEventListener("click", () => {
    if (!problemSession.current) {
      return;
    }
    hideProblemDebugHoldInfo();
    setProblemFeedback(buildProblemSolutionText(problemSession.current), "info");
    setProblemActionButtons({ showNext: true, showRepeat: false, showSolution: false });
  });
  const startDebugHold = (event) => {
    event.preventDefault();
    showProblemDebugHoldInfo();
  };
  const stopDebugHold = () => {
    hideProblemDebugHoldInfo();
  };
  el.problemDebugHoldBtn.addEventListener("pointerdown", startDebugHold);
  el.problemDebugHoldBtn.addEventListener("pointerup", stopDebugHold);
  el.problemDebugHoldBtn.addEventListener("pointerleave", stopDebugHold);
  el.problemDebugHoldBtn.addEventListener("pointercancel", stopDebugHold);
  document.addEventListener("pointerup", stopDebugHold);
  el.problemSkipBtn.addEventListener("click", showNextProblem);

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
    await handleFilterChange();
  });

  el.autoFlip.addEventListener("change", async () => {
    autoFlipEnabled = el.autoFlip.checked;
    applyBoardOrientation();
    await refreshFilteredCount();
  });

  el.ignoreTimeoutLosses.addEventListener("change", async () => {
    ignoreTimeoutLosses = el.ignoreTimeoutLosses.checked;
    await handleFilterChange();
  });

  for (const { key, input } of timeClassInputs) {
    input.addEventListener("change", async () => {
      if (!input.checked && selectedTimeClasses.size === 1 && selectedTimeClasses.has(key)) {
        input.checked = true;
        setStatus("Selecione ao menos um ritmo.", "error");
        return;
      }

      if (input.checked) {
        selectedTimeClasses.add(key);
      } else {
        selectedTimeClasses.delete(key);
      }
      await handleFilterChange();
    });
  }

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

  window.addEventListener("error", (event) => {
    const msg = event.error?.message || event.message || "Erro inesperado no frontend.";
    setStatus(`Erro no frontend: ${msg}`, "error");
  });

  window.addEventListener("unhandledrejection", (event) => {
    const msg = event.reason?.message || String(event.reason || "Erro assíncrono no frontend.");
    setStatus(`Erro no frontend: ${msg}`, "error");
  });
  window.addEventListener("resize", () => {
    if (!el.problemModalOverlay.classList.contains("hidden")) {
      ensureProblemBoardVisible();
    }
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
    problemGame = new Chess();
    problemBoard = Chessboard("problem-board", {
      position: "start",
      draggable: true,
      onDragStart: onProblemDragStart,
      onDrop: onProblemDrop,
      onSnapEnd: onProblemSnapEnd,
      pieceTheme: "/static/vendor/chessboardjs/img/chesspieces/wikipedia/{piece}.png",
    });

    updateColorFilterLabel();
    applyBoardOrientation();
    updateReplayButtons();
    await loadState(true);
    await refreshFromPosition();
  } catch (err) {
    setStatus(`Falha ao inicializar app: ${err.message}`, "error");
  }
}

main();
