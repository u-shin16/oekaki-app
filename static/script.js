/* ============================================================
   おえかきやろか - メインのJavaScript
   - お題の取得（Flaskの /api/character を fetch で呼ぶ）
   - タイマーとゲージの制御
   - 効果音（Web Audio APIで音を作るので音声ファイル不要）
   - キーボードショートカット（S / P / N）
   - ダークモード切り替え
   ============================================================ */

"use strict";

/* ------------------------------------------------------------
   1. ゲームの状態をまとめて管理するオブジェクト
   ------------------------------------------------------------ */
const state = {
  phase: "setup",      // 今の画面: setup / loading / countdown / drawing / paused / timeup / finished
  genre: "pokemon",    // お題のジャンル："pokemon" または "dataset:カテゴリ名"（"dataset:all"で全ジャンル）
  timeLimit: 30,       // 制限時間（秒）
  totalSheets: 5,      // 描く枚数（1〜10）
  autoMode: false,     // 自動モード（時間切れになったらすぐ次のお題へ進む）
  switchCountdown: false, // 絵の切りかえ時にも3秒カウントダウンを入れるか
  currentSheet: 0,     // いま何枚目か
  remainingMs: 0,      // 残り時間（ミリ秒）
  endTime: 0,          // タイマーが終わる予定の時刻（Date.now()基準）
  timerId: null,       // setIntervalのID（止めるときに使う）
  usedIds: [],         // 出題済みキャラクターのIDリスト（重複防止）
  currentCharacter: null, // いま表示中のキャラクター
  history: [],         // 今回描いたお題の記録（終了画面の一覧表示に使う）
  lastBeepSecond: null,   // 警告音を鳴らした秒（同じ秒に2回鳴らさないため）
  countdownId: null,      // 3秒カウントダウンのsetIntervalのID（途中で止めるため）
};

/* ------------------------------------------------------------
   2. よく使うHTML要素をまとめて取得しておく
   ------------------------------------------------------------ */
const el = {
  // 画面（セクション）
  screenSetup:  document.getElementById("screen-setup"),
  screenPlay:   document.getElementById("screen-play"),
  screenTimeup: document.getElementById("screen-timeup"),
  screenFinish: document.getElementById("screen-finish"),
  // 設定画面
  genreRow:     document.getElementById("genre-row"),
  timeBtns:     document.querySelectorAll(".time-btn"),
  countMinus:   document.getElementById("count-minus"),
  countPlus:    document.getElementById("count-plus"),
  countDisplay: document.getElementById("count-display"),
  startBtn:     document.getElementById("start-btn"),
  // プレイ画面
  sheetProgress: document.getElementById("sheet-progress"),
  gaugeWrap:     document.getElementById("time-gauge-wrap"),
  gauge:         document.getElementById("time-gauge"),
  loading:       document.getElementById("loading"),
  charImage:     document.getElementById("character-image"),
  charName:      document.getElementById("character-name"),
  usedCountPlay: document.getElementById("used-count-play"),
  // メニュー（☰）まわり
  menuBtn:   document.getElementById("menu-btn"),
  menuPanel: document.getElementById("menu-panel"),
  pauseBtn:  document.getElementById("pause-btn"),
  resetBtn:  document.getElementById("reset-btn"),
  homeBtn:   document.getElementById("home-btn"),
  pauseBanner: document.getElementById("pause-banner"),
  countdownOverlay: document.getElementById("countdown-overlay"),
  countdownNumber:  document.getElementById("countdown-number"),
  lastCountdown:    document.getElementById("last-countdown"),
  // 時間切れ画面
  timeupInfo: document.getElementById("timeup-info"),
  nextBtn:    document.getElementById("next-btn"),
  retryBtn:   document.getElementById("retry-btn"),
  // 終了画面
  finishInfo: document.getElementById("finish-info"),
  restartBtn: document.getElementById("restart-btn"),
  resultGrid: document.getElementById("result-grid"),
  // 拡大表示モーダル
  resultModal:      document.getElementById("result-modal"),
  resultModalImage: document.getElementById("result-modal-image"),
  resultModalName:  document.getElementById("result-modal-name"),
  resultClose:      document.getElementById("result-close"),
  // その他
  usedCount:   document.getElementById("used-count"),
  themeToggle: document.getElementById("theme-toggle"),
};

/* ------------------------------------------------------------
   3. 効果音（Web Audio APIで「ピッ」という音を作る）
   ------------------------------------------------------------ */
let audioCtx = null; // 最初のタップ時に作る（ブラウザの自動再生制限対策）

function getAudioCtx() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  // スマホでは停止状態になっていることがあるので再開する
  if (audioCtx.state === "suspended") {
    audioCtx.resume();
  }
  return audioCtx;
}

/**
 * 指定した高さ・長さのビープ音を鳴らす
 * @param {number} freq     周波数（Hz）高いほど高い音
 * @param {number} duration 長さ（秒）
 * @param {number} delay    鳴らすまでの待ち時間（秒）
 */
function beep(freq, duration, delay = 0) {
  try {
    const ctx = getAudioCtx();
    const osc = ctx.createOscillator();   // 音の元（発振器）
    const gain = ctx.createGain();        // 音量調整
    osc.type = "square";                  // ゲームっぽいピコピコ音
    osc.frequency.value = freq;
    // 音量をだんだん小さくして「ピッ」というキレを出す
    const start = ctx.currentTime + delay;
    gain.gain.setValueAtTime(0.15, start);
    gain.gain.exponentialRampToValueAtTime(0.001, start + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(start);
    osc.stop(start + duration);
  } catch (e) {
    // 音が鳴らせない環境でもゲーム自体は続けられるようにする
    console.warn("効果音を再生できませんでした", e);
  }
}

// 残り5秒の警告音（高いピッ）
// ※音が鳴るのは「残り5秒になった瞬間」のこの1回だけ
function playWarnSound() {
  beep(880, 0.3);
}

/* ------------------------------------------------------------
   4. 画面の切り替え
   ------------------------------------------------------------ */
function showScreen(name) {
  // いったん全部隠してから、指定された画面だけ表示する
  el.screenSetup.classList.add("hidden");
  el.screenPlay.classList.add("hidden");
  el.screenTimeup.classList.add("hidden");
  el.screenFinish.classList.add("hidden");

  if (name === "setup")  el.screenSetup.classList.remove("hidden");
  if (name === "play")   el.screenPlay.classList.remove("hidden");
  if (name === "timeup") el.screenTimeup.classList.remove("hidden");
  if (name === "finish") el.screenFinish.classList.remove("hidden");

  // プレイ中だけbodyに .playing を付ける
  // → CSS側でヘッダー・フッターを隠して全画面レイアウトになる
  document.body.classList.toggle("playing", name === "play");

  // 画面が変わったらメニューは閉じておく
  closeMenu();
}

// 出題済みキャラクター数の表示を更新する
function updateUsedCount() {
  const text = `出題ずみ：${state.usedIds.length}体`;
  el.usedCount.textContent = text;
  el.usedCountPlay.textContent = text;
}

// 「1 / 5 まいめ」の表示を更新する
function updateSheetProgress() {
  el.sheetProgress.textContent = `${state.currentSheet} / ${state.totalSheets} まいめ`;
}

/* ------------------------------------------------------------
   5. お題キャラクターの取得（Flask経由でPokeAPIから）
   ------------------------------------------------------------ */
// state.genre（"pokemon" または "dataset:カテゴリ名"）から、お題取得APIのURLを組み立てる
function buildCharacterUrl(exclude) {
  if (state.genre === "pokemon") {
    return `/api/character?source=pokemon&exclude=${exclude}`;
  }
  // "dataset:動物" → カテゴリ="動物"、"dataset:all" → 全ジャンル（カテゴリ指定なし）
  const category = state.genre.slice("dataset:".length);
  const categoryParam = category === "all" ? "" : `&category=${encodeURIComponent(category)}`;
  return `/api/character?source=dataset${categoryParam}&exclude=${exclude}`;
}

async function fetchCharacter() {
  state.phase = "loading";

  // 読み込み中の表示に切り替える
  el.loading.classList.remove("hidden");
  el.charImage.classList.add("hidden");
  el.charName.textContent = "";

  // 出題済みIDをカンマ区切りにしてサーバーに渡す（重複防止）
  const exclude = state.usedIds.join(",");
  const url = buildCharacterUrl(exclude);

  const res = await fetch(url);
  // エラーのときもサーバーはJSONで理由を返してくるので、まず中身を読む
  const character = await res.json().catch(() => null);
  if (!res.ok || !character || character.error) {
    // サーバーが理由を教えてくれていればそれを表示する
    const reason = character && character.error
      ? character.error
      : "サーバーからお題を取得できませんでした";
    throw new Error(reason);
  }

  // 出題済みリストに追加して、状態を更新する
  state.currentCharacter = character;
  state.usedIds.push(character.id);
  updateUsedCount();

  // 画像の読み込みが終わるまで待つ（真っ白なまま始まらないように）
  await new Promise((resolve) => {
    el.charImage.onload = resolve;
    el.charImage.onerror = resolve; // 画像が無いポケモンでも止まらないように
    el.charImage.src = character.image;
    el.charImage.alt = `お題：${character.name}`;
  });

  // 読み込み表示を消して、キャラクターを表示する
  el.loading.classList.add("hidden");
  el.charImage.classList.remove("hidden");
  el.charName.textContent = character.name;
}

/* ------------------------------------------------------------
   6. 開始前の3秒カウントダウン（3 → 2 → 1）
   ------------------------------------------------------------ */
function startCountdown(callback) {
  state.phase = "countdown";
  let count = 3;

  // このカウントダウンでは音を鳴らさない（音が鳴るのは残り5秒からだけ）
  el.countdownNumber.textContent = count;
  el.countdownOverlay.classList.remove("hidden");

  state.countdownId = setInterval(() => {
    count--;
    if (count > 0) {
      el.countdownNumber.textContent = count;
    } else {
      // カウント終了 → オーバーレイを消して本番タイマー開始
      stopCountdown();
      callback();
    }
  }, 1000);
}

// 3秒カウントダウンを途中でやめる（リセット・ホームに戻る用）
function stopCountdown() {
  if (state.countdownId !== null) {
    clearInterval(state.countdownId);
    state.countdownId = null;
  }
  el.countdownOverlay.classList.add("hidden");
}

/* ------------------------------------------------------------
   7. メインタイマー（残り時間ゲージの制御）
   ------------------------------------------------------------ */
function startTimer() {
  state.phase = "drawing";
  state.remainingMs = state.timeLimit * 1000;
  state.lastBeepSecond = null;
  el.pauseBtn.textContent = "⏸ 一時停止";
  el.pauseBtn.setAttribute("aria-label", "タイマーを一時停止する（Pキー）");
  resumeTimer();
}

// タイマーを動かし始める（再開にも使う）
function resumeTimer() {
  state.endTime = Date.now() + state.remainingMs;
  // 0.1秒ごとに残り時間をチェックしてゲージを更新する
  state.timerId = setInterval(tick, 100);
  tick(); // すぐ1回実行して表示のズレをなくす
}

// タイマーを止める（一時停止・リセット用）
function stopTimer() {
  if (state.timerId !== null) {
    clearInterval(state.timerId);
    state.timerId = null;
  }
}

// 0.1秒ごとに呼ばれる処理
function tick() {
  state.remainingMs = Math.max(0, state.endTime - Date.now());
  const remainingSec = state.remainingMs / 1000;

  // --- ゲージの幅を残り時間の割合で更新 ---
  const percent = (state.remainingMs / (state.timeLimit * 1000)) * 100;
  el.gauge.style.width = `${percent}%`;
  el.gaugeWrap.setAttribute("aria-valuenow", Math.round(percent));

  // --- 残り時間によってゲージの色を変える ---
  el.gauge.classList.remove("warn", "danger");
  if (remainingSec <= 5) {
    el.gauge.classList.add("danger");     // 残り5秒：赤
  } else if (remainingSec <= 10) {
    el.gauge.classList.add("warn");       // 残り10秒：オレンジ
  }

  // --- 残り5秒から：右下に数字カウントダウン（5,4,3,2,1） ---
  if (remainingSec <= 5 && remainingSec > 0) {
    const displaySec = Math.ceil(remainingSec); // 5,4,3,2,1
    el.lastCountdown.classList.remove("hidden");
    el.lastCountdown.textContent = displaySec;
    // 音を鳴らすのは「残り5秒になった瞬間」の1回だけ（4,3,2,1は表示のみ）
    if (state.lastBeepSecond !== displaySec) {
      state.lastBeepSecond = displaySec;
      if (displaySec === 5) playWarnSound();
    }
  } else {
    el.lastCountdown.classList.add("hidden");
  }

  // --- 時間切れ ---
  if (state.remainingMs <= 0) {
    stopTimer();
    onTimeUp();
  }
}

// 時間切れになったときの処理
function onTimeUp() {
  state.phase = "timeup";
  el.lastCountdown.classList.add("hidden");

  // 描き終わったお題を記録する（同じお題のやり直しでも上書きされるだけ）
  state.history[state.currentSheet - 1] = state.currentCharacter;

  const isLast = state.currentSheet >= state.totalSheets;

  // 自動モード：タイムアップ画面は出さずに、すぐ次のお題（最後なら終了画面）へ
  if (state.autoMode) {
    if (isLast) {
      finishGame();
    } else {
      state.currentSheet++;
      startSheet();
    }
    return;
  }

  el.timeupInfo.textContent =
    `${state.currentSheet} / ${state.totalSheets} まいめ「${state.currentCharacter.name}」でした`;

  // 最後の1枚なら「次のお題」を「けっか発表」に変える
  if (isLast) {
    el.nextBtn.textContent = "🎉 おわり！";
    el.nextBtn.setAttribute("aria-label", "終了画面へ進む（Nキー）");
  } else {
    el.nextBtn.textContent = "▶ 次のお題";
    el.nextBtn.setAttribute("aria-label", "次のお題を表示する（Nキー）");
  }
  showScreen("timeup");
}

/* ------------------------------------------------------------
   8. ゲームの進行（スタート・次のお題・リセットなど）
   ------------------------------------------------------------ */

// 1枚分をスタートする（お題取得 → 3秒カウント → タイマー開始）
async function startSheet() {
  showScreen("play");
  updateSheetProgress();
  // ゲージを満タンに戻しておく
  el.gauge.style.width = "100%";
  el.gauge.classList.remove("warn", "danger");

  try {
    await fetchCharacter();
  } catch (e) {
    // 通信エラーのときはメッセージを出して設定画面に戻る
    alert(`お題を取得できませんでした。\n${e.message}`);
    resetGame();
    return;
  }
  // 読み込み中に「ホームに戻る」が押されていたら、ここで中断する
  if (state.phase !== "loading") return;

  if (state.currentSheet === 1 || state.switchCountdown) {
    // 最初の1枚はいつも3秒カウントダウンをはさむ
    // 2枚目以降は設定「切りかえカウントダウン：あり」のときだけはさむ
    startCountdown(startTimer);
  } else {
    // 「なし」のときは、絵が切り替わったらすぐ開始
    startTimer();
  }
}

// スタートボタン：ゲーム開始
function startGame() {
  if (state.phase !== "setup") return;
  getAudioCtx(); // ユーザー操作のタイミングで音の準備をしておく
  state.currentSheet = 1;
  state.history = []; // 前回の記録はクリアする
  startSheet();
}

// 次のお題ボタン（最後の1枚のあとは終了画面へ）
function nextSheet() {
  if (state.phase !== "timeup") return;
  if (state.currentSheet >= state.totalSheets) {
    finishGame();
  } else {
    state.currentSheet++;
    startSheet();
  }
}

// 同じお題でもう一度ボタン（キャラクターはそのまま、タイマーだけやり直す）
function retrySameSheet() {
  if (state.phase !== "timeup") return;
  showScreen("play");
  updateSheetProgress();
  el.gauge.style.width = "100%";
  el.gauge.classList.remove("warn", "danger");
  startCountdown(startTimer);
}

// 一時停止 ⇔ 再開の切り替え
function togglePause() {
  if (state.phase === "drawing") {
    // 一時停止する
    stopTimer();
    state.remainingMs = Math.max(0, state.endTime - Date.now());
    state.phase = "paused";
    el.pauseBtn.textContent = "▶ さいかい";
    el.pauseBtn.setAttribute("aria-label", "タイマーを再開する（Pキー）");
    el.pauseBanner.classList.remove("hidden"); // 「一時停止中」バナーを表示
  } else if (state.phase === "paused") {
    // 再開する
    state.phase = "drawing";
    el.pauseBtn.textContent = "⏸ 一時停止";
    el.pauseBtn.setAttribute("aria-label", "タイマーを一時停止する（Pキー）");
    el.pauseBanner.classList.add("hidden");
    resumeTimer();
  }
}

// リセット：いまのお題を最初からやりなおす（キャラクターはそのまま）
function resetCurrentSheet() {
  // 描いている途中か一時停止中だけ有効
  if (state.phase !== "drawing" && state.phase !== "paused") return;
  stopTimer();
  el.pauseBanner.classList.add("hidden");
  el.pauseBtn.textContent = "⏸ 一時停止";
  el.pauseBtn.setAttribute("aria-label", "タイマーを一時停止する（Pキー）");
  el.lastCountdown.classList.add("hidden");
  // ゲージを満タンに戻して3秒カウントからやりなおす
  el.gauge.style.width = "100%";
  el.gauge.classList.remove("warn", "danger");
  startCountdown(startTimer);
}

// ホームに戻る：タイマーを止めて設定画面に戻る（出題履歴もリセット）
function resetGame() {
  stopTimer();
  stopCountdown();
  state.phase = "setup";
  state.currentSheet = 0;
  state.usedIds = [];
  state.currentCharacter = null;
  updateUsedCount();
  el.lastCountdown.classList.add("hidden");
  el.pauseBanner.classList.add("hidden");
  el.pauseBtn.textContent = "⏸ 一時停止";
  closeResultModal(); // 拡大表示が開いたままなら閉じる
  showScreen("setup");
}

// 全枚数終了：おつかれさま画面を表示
function finishGame() {
  state.phase = "finished";
  el.finishInfo.textContent =
    `${state.totalSheets}枚 かききった！ すごい！`;
  buildResultGrid(); // 今回描いたお題を一覧表示する
  showScreen("finish");
}

/* ------------------------------------------------------------
   8.5 結果の一覧表示と拡大表示（終了画面）
   ------------------------------------------------------------ */

// 今回描いたお題をグリッドに並べる
function buildResultGrid() {
  el.resultGrid.innerHTML = ""; // 前回の表示を消す

  state.history.forEach((character, index) => {
    if (!character) return; // 念のため（記録が抜けていたら飛ばす）

    // 1項目 = ボタン（押すと拡大表示できる）
    const item = document.createElement("button");
    item.type = "button";
    item.className = "result-item";
    item.setAttribute("role", "listitem");
    item.setAttribute(
      "aria-label",
      `${index + 1}まいめ ${character.name} を大きく表示する`
    );

    const img = document.createElement("img");
    img.src = character.image;
    img.alt = ""; // 名前はラベルで読むので画像は飾り扱い
    img.loading = "lazy";

    const label = document.createElement("span");
    label.className = "result-label";
    label.textContent = `${index + 1}. ${character.name}`;

    item.appendChild(img);
    item.appendChild(label);
    item.addEventListener("click", () => openResultModal(character));
    el.resultGrid.appendChild(item);
  });
}

// 拡大表示を開く
function openResultModal(character) {
  el.resultModalImage.src = character.image;
  el.resultModalImage.alt = character.name;
  el.resultModalName.textContent = character.name;
  el.resultModal.classList.remove("hidden");
  el.resultClose.focus(); // キーボード操作でもすぐ閉じられるように
}

// 拡大表示を閉じる
function closeResultModal() {
  el.resultModal.classList.add("hidden");
}

// 終了画面から：設定画面に戻ってもう一度
function restartGame() {
  resetGame();
}

/* ------------------------------------------------------------
   9. 設定画面の操作（制限時間・枚数）
   ------------------------------------------------------------ */

// 制限時間ボタン：押したボタンだけ選択状態にする
el.timeBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    el.timeBtns.forEach((b) => {
      b.classList.remove("selected");
      b.setAttribute("aria-checked", "false");
    });
    btn.classList.add("selected");
    btn.setAttribute("aria-checked", "true");
    state.timeLimit = Number(btn.dataset.time);
  });
});

// ジャンルボタン：押したものだけ選択状態にする
// （ポケモン・ぜんぶは最初からHTMLにあり、ほかはloadGenres()で後から追加される。
//   親要素でクリックを拾う「イベント委任」なので、後から増えたボタンにも効く）
if (el.genreRow) {
  el.genreRow.addEventListener("click", (e) => {
    const btn = e.target.closest(".genre-btn");
    if (!btn) return;
    document.querySelectorAll(".genre-btn").forEach((b) => {
      b.classList.remove("selected");
      b.setAttribute("aria-checked", "false");
    });
    btn.classList.add("selected");
    btn.setAttribute("aria-checked", "true");
    state.genre = btn.dataset.genre;
  });
}

// カテゴリ名 → 絵文字アイコンの対応表（見た目をそろえるため）
// 表にない名前が来ても🖼️（絵札）を使うので、データセット側の追加にも耐えられる
const GENRE_ICONS = {
  "動物": "🐾",
  "昆虫": "🐛",
  "食べ物": "🍙",
  "乗り物": "🚗",
  "建物": "🏛️",
  "植物": "🌿",
};

// カテゴリ名 → 写真タイル画像の対応表
const GENRE_TILE_FILES = {
  "動物": "animal.webp",
  "昆虫": "insect.webp",
  "食べ物": "food.webp",
  "乗り物": "vehicle.webp",
  "建物": "building.webp",
  "植物": "plant.webp",
};

const HIDDEN_GENRE_CATEGORIES = new Set(["スポーツ用品", "スポーツ用具", "道具", "楽器"]);

// サーバーのお題データセットからジャンル一覧を取ってきて、
// 「ポケモン」「ぜんぶ」の後ろに写真タイルのボタンを追加する
async function loadGenres() {
  if (!el.genreRow) return;

  try {
    const res = await fetch("/api/genres");
    const data = await res.json();
    (data.categories || []).forEach((category) => {
      if (HIDDEN_GENRE_CATEGORIES.has(category)) return;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "genre-btn";
      btn.dataset.genre = `dataset:${category}`;
      btn.setAttribute("role", "radio");
      btn.setAttribute("aria-checked", "false");
      btn.setAttribute("aria-label", `ジャンルを${category}にする`);

      const tileFile = GENRE_TILE_FILES[category];
      if (tileFile) {
        const img = document.createElement("img");
        img.src = `/static/genre_tiles/${tileFile}`;
        img.alt = "";
        img.setAttribute("aria-hidden", "true");
        btn.appendChild(img);
      } else {
        btn.classList.add("icon-fallback");

        const icon = document.createElement("span");
        icon.className = "genre-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = GENRE_ICONS[category] || "🖼️";

        const label = document.createElement("span");
        label.className = "genre-label";
        label.textContent = category;

        btn.appendChild(icon);
        btn.appendChild(label);
      }
      el.genreRow.appendChild(btn);
    });
  } catch (e) {
    // 取得できなくても致命的ではない（ポケモン・ぜんぶは変わらず使える）
    console.warn("ジャンル一覧の取得に失敗しました", e);
  }
}

// 自動モードのオン／オフボタン：押したほうだけ選択状態にする
document.querySelectorAll(".auto-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".auto-btn").forEach((b) => {
      b.classList.remove("selected");
      b.setAttribute("aria-checked", "false");
    });
    btn.classList.add("selected");
    btn.setAttribute("aria-checked", "true");
    state.autoMode = btn.dataset.auto === "on";
  });
});

// 切りかえカウントダウンのなし／ありボタン：押したほうだけ選択状態にする
document.querySelectorAll(".cd-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".cd-btn").forEach((b) => {
      b.classList.remove("selected");
      b.setAttribute("aria-checked", "false");
    });
    btn.classList.add("selected");
    btn.setAttribute("aria-checked", "true");
    state.switchCountdown = btn.dataset.cd === "on";
  });
});

// 枚数の−ボタン（最小1枚）
el.countMinus.addEventListener("click", () => {
  if (state.totalSheets > 1) {
    state.totalSheets--;
    el.countDisplay.textContent = `${state.totalSheets}枚`;
  }
});

// 枚数の＋ボタン（最大10枚）
el.countPlus.addEventListener("click", () => {
  if (state.totalSheets < 10) {
    state.totalSheets++;
    el.countDisplay.textContent = `${state.totalSheets}枚`;
  }
});

/* ------------------------------------------------------------
   10. メニュー（☰）の開閉
   ------------------------------------------------------------ */
function openMenu() {
  el.menuPanel.classList.remove("hidden");
  el.menuBtn.setAttribute("aria-expanded", "true");
  el.menuBtn.setAttribute("aria-label", "メニューを閉じる");
}

function closeMenu() {
  el.menuPanel.classList.add("hidden");
  el.menuBtn.setAttribute("aria-expanded", "false");
  el.menuBtn.setAttribute("aria-label", "メニューを開く");
}

el.menuBtn.addEventListener("click", (e) => {
  e.stopPropagation(); // 下の「外をタップしたら閉じる」が同時に動かないように
  if (el.menuPanel.classList.contains("hidden")) {
    openMenu();
  } else {
    closeMenu();
  }
});

// メニューの外をタップしたら閉じる
document.addEventListener("click", (e) => {
  if (!el.menuPanel.classList.contains("hidden") && !e.target.closest(".menu-wrap")) {
    closeMenu();
  }
});

/* ------------------------------------------------------------
   11. ボタンのイベント登録
   ------------------------------------------------------------ */
el.startBtn.addEventListener("click", startGame);
// メニューの中の3つのボタン（押したらメニューを閉じる）
el.pauseBtn.addEventListener("click", () => { togglePause(); closeMenu(); });
el.resetBtn.addEventListener("click", () => { resetCurrentSheet(); closeMenu(); });
el.homeBtn.addEventListener("click", () => { resetGame(); });
// 一時停止中バナーをタップしたら再開
el.pauseBanner.addEventListener("click", togglePause);
el.nextBtn.addEventListener("click", nextSheet);
el.retryBtn.addEventListener("click", retrySameSheet);
el.restartBtn.addEventListener("click", restartGame);
// 拡大表示：✕ボタンでも、画面のどこを押しても閉じられる
el.resultClose.addEventListener("click", closeResultModal);
el.resultModal.addEventListener("click", closeResultModal);

/* ------------------------------------------------------------
   12. キーボードショートカット（S / P / N）
   ------------------------------------------------------------ */
document.addEventListener("keydown", (e) => {
  // 修飾キー（Ctrlなど）と一緒のときは何もしない
  if (e.ctrlKey || e.metaKey || e.altKey) return;

  // 拡大表示が開いているときは、どのキーでも閉じるだけにする
  if (!el.resultModal.classList.contains("hidden")) {
    closeResultModal();
    return;
  }

  const key = e.key.toLowerCase();
  if (key === "s") {
    // Sキー：スタート（設定画面）／もういちど（終了画面）
    if (state.phase === "setup") startGame();
    else if (state.phase === "finished") restartGame();
  } else if (key === "p") {
    // Pキー：一時停止 ⇔ 再開
    togglePause();
  } else if (key === "n") {
    // Nキー：次のお題（時間切れ画面のみ）
    nextSheet();
  }
});

/* ------------------------------------------------------------
   13. ダークモード切り替え（好みをlocalStorageに保存）
   ------------------------------------------------------------ */
function applyTheme(dark) {
  document.body.classList.toggle("dark", dark);
  el.themeToggle.textContent = dark ? "☀️" : "🌙";
  localStorage.setItem("oekaki-theme", dark ? "dark" : "light");
}

el.themeToggle.addEventListener("click", () => {
  applyTheme(!document.body.classList.contains("dark"));
});

// 前回の設定があれば復元。なければOSの設定に合わせる
const savedTheme = localStorage.getItem("oekaki-theme");
if (savedTheme) {
  applyTheme(savedTheme === "dark");
} else {
  applyTheme(window.matchMedia("(prefers-color-scheme: dark)").matches);
}

/* ------------------------------------------------------------
   14. 初期表示
   ------------------------------------------------------------ */
el.countDisplay.textContent = `${state.totalSheets}枚`;
updateUsedCount();
showScreen("setup");
loadGenres(); // ジャンルのボタンをサーバーの一覧から追加する
