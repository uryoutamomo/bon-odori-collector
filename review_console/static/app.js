const state = {
  view: "home",
  inventory: null,
  adminSummary: null,
  opsMetrics: null,
  collectionStatus: null,
  stageStatus: null,
  undoStatus: null,
  status: "pending",
  source: "",
  domain: "",
  actionGroup: "",
  q: "",
  limit: "250",
  activeIndex: 0,
  itemsLoaded: false,
  currentItems: [],
  savingItemIds: new Set(),
};

const labels = {
  accept: "レビュー採用",
  reject: "却下",
  hold: "保留",
  needs_research: "要調査",
};

const elements = {
  lastUpdated: document.querySelector("#lastUpdated"),
  viewTabs: Array.from(document.querySelectorAll(".view-tab")),
  homeView: document.querySelector("#homeView"),
  collectionView: document.querySelector("#collectionView"),
  metricsView: document.querySelector("#metricsView"),
  reviewView: document.querySelector("#reviewView"),
  homeUpdated: document.querySelector("#homeUpdated"),
  homePendingCount: document.querySelector("#homePendingCount"),
  homeReviewedCount: document.querySelector("#homeReviewedCount"),
  homeStageCount: document.querySelector("#homeStageCount"),
  homeStageLabel: document.querySelector("#homeStageLabel"),
  homeYoutubeCandidates: document.querySelector("#homeYoutubeCandidates"),
  homeMissingSource: document.querySelector("#homeMissingSource"),
  homeMissingVenue: document.querySelector("#homeMissingVenue"),
  attentionCount: document.querySelector("#attentionCount"),
  attentionList: document.querySelector("#attentionList"),
  todayActions: document.querySelector("#todayActions"),
  opsSnapshotDate: document.querySelector("#opsSnapshotDate"),
  opsSummary: document.querySelector("#opsSummary"),
  openPendingButton: document.querySelector("#openPendingButton"),
  collectionUpdated: document.querySelector("#collectionUpdated"),
  collectionLanes: document.querySelector("#collectionLanes"),
  reloadCollectionButton: document.querySelector("#reloadCollectionButton"),
  metricsUpdated: document.querySelector("#metricsUpdated"),
  metricCards: document.querySelector("#metricCards"),
  trendCharts: document.querySelector("#trendCharts"),
  historyCount: document.querySelector("#historyCount"),
  historyTable: document.querySelector("#historyTable"),
  openMetricsReviewButton: document.querySelector("#openMetricsReviewButton"),
  totalCount: document.querySelector("#totalCount"),
  pendingCount: document.querySelector("#pendingCount"),
  reviewedCount: document.querySelector("#reviewedCount"),
  closedCount: document.querySelector("#closedCount"),
  actionGroupFilters: document.querySelector("#actionGroupFilters"),
  domainFilters: document.querySelector("#domainFilters"),
  sourceList: document.querySelector("#sourceList"),
  items: document.querySelector("#items"),
  listTitle: document.querySelector("#listTitle"),
  listSummary: document.querySelector("#listSummary"),
  message: document.querySelector("#message"),
  stageNotice: document.querySelector("#stageNotice"),
  undoButton: document.querySelector("#undoButton"),
  searchInput: document.querySelector("#searchInput"),
  limitSelect: document.querySelector("#limitSelect"),
  detailDialog: document.querySelector("#detailDialog"),
  detailTitle: document.querySelector("#detailTitle"),
  detailRaw: document.querySelector("#detailRaw"),
  helpDialog: document.querySelector("#helpDialog"),
};

const metricCardKeys = [
  "youtube_candidates_total",
  "youtube_candidates_strong",
  "youtube_candidates_review",
  "youtube_candidates_weak",
  "youtube_run_remaining_after",
  "low_confidence_review_unreviewed_rows",
  "registered_events_incomplete",
  "missing_venue_occurrences",
  "missing_source_url_occurrences",
  "missing_date_start_count",
  "public_date_prediction_applied",
  "public_historical_reference_applied",
  "public_season_hint_applied",
];

const metricCharts = [
  {
    title: "YouTube候補",
    note: "total / strong / review / weak の増減を見ます。weakだけ増える日は検索条件の見直し候補です。",
    keys: ["youtube_candidates_total", "youtube_candidates_strong", "youtube_candidates_review", "youtube_candidates_weak"],
    colors: ["#2563eb", "#0f766e", "#a15c07", "#475467"],
  },
  {
    title: "レビュー・正本整備",
    note: "減ってほしい残作業です。横ばいならレビューか個別applyが詰まっています。",
    keys: [
      "low_confidence_review_unreviewed_rows",
      "registered_events_incomplete",
      "missing_venue_occurrences",
      "missing_source_url_occurrences",
      "missing_date_start_count",
    ],
    colors: ["#b42318", "#6941c6", "#0e7490", "#b54708", "#475467"],
  },
  {
    title: "公開補助",
    note: "日付予測、過去実績、季節ヒントの表示量です。急変した日は公開表示を確認します。",
    keys: ["public_date_prediction_applied", "public_historical_reference_applied", "public_season_hint_applied"],
    colors: ["#2563eb", "#4f8f8b", "#946200"],
  },
];

const historyTableKeys = [
  "snapshot_date",
  "youtube_candidates_total",
  "youtube_candidates_strong",
  "youtube_candidates_review",
  "youtube_candidates_weak",
  "youtube_run_remaining_after",
  "registered_events_incomplete",
  "missing_venue_occurrences",
  "missing_source_url_occurrences",
  "missing_date_start_count",
  "public_date_prediction_applied",
  "public_historical_reference_applied",
  "public_season_hint_applied",
];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function showMessage(text) {
  elements.message.textContent = text;
  elements.message.hidden = false;
  window.clearTimeout(showMessage.timer);
  showMessage.timer = window.setTimeout(() => {
    elements.message.hidden = true;
  }, 5200);
}

async function loadInventory(options = {}) {
  const refreshItems = options.refreshItems ?? state.view === "review";
  const [inventory, stageStatus] = await Promise.all([
    api("/api/inventory"),
    api("/api/stage-status"),
  ]);
  state.inventory = inventory;
  state.stageStatus = stageStatus;
  renderInventory();
  renderStageNotice();
  if (refreshItems) {
    await loadItems();
  } else {
    state.itemsLoaded = false;
  }
}

async function loadUndoStatus() {
  state.undoStatus = await api("/api/undo-status");
  renderUndoButton();
}

async function loadAdminSummary() {
  state.adminSummary = await api("/api/admin-summary");
  renderHome();
}

async function loadOpsMetrics() {
  state.opsMetrics = await api("/api/ops-metrics");
  renderMetrics();
}

async function loadCollectionStatus() {
  state.collectionStatus = await api("/api/collection-status");
  renderCollectionStatus();
}

async function refreshCurrentView() {
  await loadInventory();
  await loadUndoStatus();
  await loadAdminSummary();
  if (state.view === "collection") {
    await loadCollectionStatus();
  }
  if (state.view === "metrics") {
    await loadOpsMetrics();
  }
}

function setView(view) {
  state.view = view;
  elements.homeView.hidden = view !== "home";
  elements.collectionView.hidden = view !== "collection";
  elements.metricsView.hidden = view !== "metrics";
  elements.reviewView.hidden = view !== "review";
  elements.viewTabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  if (view === "review") {
    if (state.itemsLoaded) {
      setActiveIndex(state.activeIndex, { scroll: false });
    } else {
      loadItems().catch((error) => {
        showMessage(error.message);
        console.error(error);
      });
    }
  }
  if (view === "metrics") {
    loadOpsMetrics().catch((error) => {
      showMessage(error.message);
      console.error(error);
    });
  }
  if (view === "collection") {
    loadCollectionStatus().catch((error) => {
      showMessage(error.message);
      console.error(error);
    });
  }
}

function renderHome() {
  const summary = state.adminSummary;
  if (!summary) return;
  const review = summary.review || {};
  const stage = summary.stage || {};
  const ops = summary.ops || {};
  elements.homeUpdated.textContent = [
    `更新 ${formatDate(summary.generated_at)}`,
    ops.snapshot_date ? `snapshot ${ops.snapshot_date}` : "",
  ].filter(Boolean).join(" / ");
  elements.homePendingCount.textContent = numberText(review.pending);
  elements.homeReviewedCount.textContent = numberText(review.reviewed);
  elements.homeStageCount.textContent = numberText(stage.decision_count);
  elements.homeStageLabel.textContent = stage.label || "反映待ちなし";
  elements.homeYoutubeCandidates.textContent = numberText(ops.youtube_candidates_total);
  elements.homeMissingSource.textContent = numberText(ops.missing_source_url_occurrences);
  elements.homeMissingVenue.textContent = numberText(ops.missing_venue_occurrences);
  renderAttention(summary.attention || []);
  renderTodayActions(summary);
  renderOpsSummary(ops);
}

function renderAttention(attention) {
  elements.attentionCount.textContent = attention.length;
  if (!attention.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "今日の注意はありません。";
    elements.attentionList.replaceChildren(empty);
    return;
  }
  elements.attentionList.replaceChildren(...attention.map((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `attention-card ${item.level || "info"}`;
    button.innerHTML = `
      <span>${escapeHtml(item.level || "info")}</span>
      <strong>${escapeHtml(item.title || "")}</strong>
      <small>${escapeHtml(attentionValueText(item.value))}${item.message ? ` / ${escapeHtml(item.message)}` : ""}</small>
    `;
    button.addEventListener("click", () => applyTarget(item.target || {}));
    return button;
  }));
}

function renderTodayActions(summary) {
  const review = summary.review || {};
  const ops = summary.ops || {};
  const actionGroups = state.inventory?.action_group_counts || {};
  const actions = [
    {
      title: "未レビューを見る",
      value: review.pending,
      target: { view: "review", status: "pending" },
    },
    {
      title: "曲候補待ちを見る",
      value: actionGroups.song_research?.pending,
      target: { view: "review", actionGroup: "song_research", status: "pending" },
    },
    {
      title: "根拠URL不足を確認",
      value: ops.missing_source_url_occurrences,
      target: { view: "review", actionGroup: "source_url", status: "pending" },
    },
    {
      title: "会場不足レビューを見る",
      value: ops.missing_venue_occurrences,
      target: { view: "review", actionGroup: "venue", status: "pending" },
    },
    {
      title: "同一イベント確認を見る",
      value: ops.youtube_review_queue_undecided_groups,
      target: { view: "review", actionGroup: "identity", status: "pending" },
    },
    {
      title: "日付確認待ちを見る",
      value: ops.missing_date_start_count,
      target: { view: "review", actionGroup: "current_date", status: "pending" },
    },
  ].filter((item) => Number(item.value || 0) > 0);

  if (!actions.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "優先アクションはありません。";
    elements.todayActions.replaceChildren(empty);
    return;
  }

  elements.todayActions.replaceChildren(...actions.map((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "action-card";
    button.innerHTML = `
      <strong>${escapeHtml(item.title)}</strong>
      <span class="badge">${numberText(item.value)}</span>
    `;
    button.addEventListener("click", () => applyTarget(item.target));
    return button;
  }));
}

function renderOpsSummary(ops) {
  elements.opsSnapshotDate.textContent = ops.snapshot_date ? `snapshot ${ops.snapshot_date}` : "";
  const rows = [
    ["YouTube状態", ops.youtube_run_status || "unknown"],
    ["今回選択", ops.youtube_run_selected_rows],
    ["完了バッチ", ops.youtube_run_completed_batches],
    ["残り", `${numberText(ops.youtube_run_remaining_before)} -> ${numberText(ops.youtube_run_remaining_after)}`],
    ["候補 total", ops.youtube_candidates_total],
    ["strong", ops.youtube_candidates_strong],
    ["review", ops.youtube_candidates_review],
    ["weak", ops.youtube_candidates_weak],
    ["登録済み不完全", ops.registered_events_incomplete],
    ["missing date_start", ops.missing_date_start_count],
    ["日付予測", ops.public_date_prediction_applied],
    ["過去実績表示", ops.public_historical_reference_applied],
    ["季節ヒント", ops.public_season_hint_applied],
  ];
  elements.opsSummary.replaceChildren(...rows.map(([label, value]) => {
    const div = document.createElement("div");
    div.className = "ops-item";
    div.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(numberText(value))}</strong>`;
    return div;
  }));
}

function renderMetrics() {
  const payload = state.opsMetrics;
  if (!payload) return;
  const current = payload.current || {};
  const history = payload.history || [];
  const labels = metricLabels(payload.trend_metrics || []);
  elements.metricsUpdated.textContent = [
    `更新 ${formatDate(payload.generated_at)}`,
    current.snapshot_date ? `snapshot ${current.snapshot_date}` : "",
    history.length ? `${history.length}件` : "",
  ].filter(Boolean).join(" / ");
  elements.historyCount.textContent = history.length;
  renderMetricCards(current, payload.deltas || {}, labels, payload.trend_metrics || []);
  renderTrendCharts(history, labels);
  renderHistoryTable(history, labels);
}

function renderCollectionStatus() {
  const payload = state.collectionStatus;
  if (!payload) return;
  elements.collectionUpdated.textContent = `更新 ${formatDate(payload.generated_at)}`;
  elements.collectionLanes.replaceChildren(...(payload.lanes || []).map((lane) => renderCollectionLane(lane, payload.links || {})));
}

function renderCollectionLane(lane, links) {
  const section = document.createElement("section");
  section.className = `collection-lane ${lane.id || ""}`;
  const linkButtons = lane.id === "youtube"
    ? [
        externalButton("PR #3", links.youtube_pr),
        externalButton("YouTube workflow", links.youtube_workflow),
      ]
    : [
        externalButton("collect workflow", links.collect_workflow),
        externalButton("X候補workflow", links.review_x_workflow),
        externalButton("X graph workflow", links.discover_x_workflow),
      ];
  section.innerHTML = `
    <div class="collection-lane-head">
      <div>
        <h2>${escapeHtml(lane.title || "")}</h2>
        <p>${escapeHtml(lane.status || "")}</p>
      </div>
      <div class="collection-links"></div>
    </div>
    <div class="collection-summary">
      ${(lane.summary || []).map((item) => `
        <div class="collection-metric">
          <span>${escapeHtml(item.label || "")}</span>
          <strong>${escapeHtml(numberText(item.value))}</strong>
        </div>
      `).join("")}
    </div>
    <div class="collection-sections">
      <section>
        <div class="panel-head"><h3>内容解読・レビュー進捗</h3></div>
        <div class="collection-source-list"></div>
      </section>
      <section>
        <div class="panel-head"><h3>出力ファイル</h3></div>
        <div class="collection-file-list"></div>
      </section>
      <section>
        <div class="panel-head"><h3>安全な起動</h3></div>
        <div class="collection-operation-list"></div>
      </section>
    </div>
  `;
  section.querySelector(".collection-links").replaceChildren(...linkButtons.filter(Boolean));
  section.querySelector(".collection-source-list").replaceChildren(...(lane.sources || []).map(renderCollectionSource));
  section.querySelector(".collection-file-list").replaceChildren(...(lane.files || []).map(renderCollectionFile));
  section.querySelector(".collection-operation-list").replaceChildren(...(lane.operations || []).map(renderCollectionOperation));
  return section;
}

function externalButton(label, url) {
  if (!url) return null;
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", () => window.open(url, "_blank", "noopener,noreferrer"));
  return button;
}

function renderCollectionSource(source) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "collection-source";
  button.innerHTML = `
    <span>${escapeHtml(source.title || source.id || "")}</span>
    <strong>${numberText(source.pending)} / ${numberText(source.total)}</strong>
    <small>未レビュー / 全件</small>
  `;
  button.addEventListener("click", () => applyTarget(source.target || { view: "review", source: source.id, status: "pending" }));
  return button;
}

function renderCollectionFile(file) {
  const div = document.createElement("div");
  div.className = `collection-file ${file.exists ? "" : "missing"}`;
  div.innerHTML = `
    <span>${escapeHtml(file.path || "")}</span>
    <strong>${escapeHtml(file.exists ? numberText(file.count) : "なし")}</strong>
    <small>${escapeHtml(file.generated_at ? `generated ${formatDate(file.generated_at)}` : file.modified_at ? `modified ${formatDate(file.modified_at)}` : "")}</small>
  `;
  return div;
}

function renderCollectionOperation(operation) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "collection-operation";
  button.innerHTML = `
    <strong>${escapeHtml(operation.label || operation.id || "")}</strong>
    <span>${escapeHtml(operation.note || "")}</span>
    <code>${escapeHtml(operation.command || "")}</code>
  `;
  button.addEventListener("click", () => runCollectionOperation(operation));
  return button;
}

async function runCollectionOperation(operation) {
  const ok = window.confirm(`${operation.label}を実行します。\n\n${operation.note}\n\n${operation.command}`);
  if (!ok) return;
  showMessage(`${operation.label}を実行中です`);
  const result = await api("/api/operation/run", {
    method: "POST",
    body: JSON.stringify({ operation_id: operation.id }),
  });
  const detail = result.result || {};
  showMessage(detail.ok ? `${operation.label}が完了しました` : `${operation.label}が失敗しました`);
  await Promise.all([
    loadInventory({ refreshItems: false }),
    loadAdminSummary(),
    loadCollectionStatus(),
  ]);
}

function metricLabels(metrics) {
  const labels = {};
  metrics.forEach((item) => {
    labels[item.key] = item.label || item.key;
  });
  labels.snapshot_date = "日付";
  return labels;
}

function metricKinds(metrics) {
  const kinds = {};
  metrics.forEach((item) => {
    kinds[item.key] = item.kind || "watch";
  });
  return kinds;
}

function renderMetricCards(current, deltas, labels, metrics) {
  const kinds = metricKinds(metrics);
  elements.metricCards.replaceChildren(...metricCardKeys.map((key) => {
    const card = document.createElement("article");
    const delta = deltas[key];
    card.className = `metric-trend-card ${deltaClass(delta, kinds[key])}`;
    card.innerHTML = `
      <span>${escapeHtml(labels[key] || key)}</span>
      <strong>${escapeHtml(numberText(current[key]))}</strong>
      <small>${escapeHtml(deltaText(delta))}</small>
    `;
    return card;
  }));
}

function renderTrendCharts(history, labels) {
  elements.trendCharts.replaceChildren(...metricCharts.map((chart) => {
    const section = document.createElement("section");
    section.className = "trend-panel";
    section.innerHTML = `
      <div class="panel-head">
        <div>
          <h2>${escapeHtml(chart.title)}</h2>
          <p>${escapeHtml(chart.note)}</p>
        </div>
      </div>
      <div class="trend-chart">${lineChartSvg(history, chart.keys, labels, chart.colors)}</div>
      <div class="trend-legend">
        ${chart.keys.map((key, index) => `
          <span><i style="background:${escapeAttr(chart.colors[index] || "#667085")}"></i>${escapeHtml(labels[key] || key)}</span>
        `).join("")}
      </div>
    `;
    return section;
  }));
}

function lineChartSvg(rows, keys, labels, colors) {
  const width = 720;
  const height = 220;
  const left = 46;
  const right = 18;
  const top = 18;
  const bottom = 34;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const points = [];
  rows.forEach((row, rowIndex) => {
    keys.forEach((key) => {
      const value = Number(row[key]);
      if (Number.isFinite(value)) points.push({ rowIndex, value });
    });
  });
  if (!rows.length || !points.length) {
    return '<div class="empty-state">履歴がまだありません。</div>';
  }
  let minValue = Math.min(0, ...points.map((point) => point.value));
  let maxValue = Math.max(...points.map((point) => point.value), 1);
  if (minValue === maxValue) {
    maxValue += 1;
  }
  const xFor = (rowIndex) => {
    if (rows.length <= 1) return left + plotWidth;
    return left + (rowIndex / (rows.length - 1)) * plotWidth;
  };
  const yFor = (value) => top + ((maxValue - value) / (maxValue - minValue)) * plotHeight;
  const parts = [
    `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeAttr(keys.map((key) => labels[key] || key).join(" / "))}">`,
    `<line x1="${left}" y1="${top}" x2="${left}" y2="${height - bottom}" class="axis"/>`,
    `<line x1="${left}" y1="${height - bottom}" x2="${width - right}" y2="${height - bottom}" class="axis"/>`,
  ];
  [0, 0.25, 0.5, 0.75, 1].forEach((fraction) => {
    const value = minValue + (maxValue - minValue) * fraction;
    const y = yFor(value);
    parts.push(`<line x1="${left}" y1="${y.toFixed(1)}" x2="${width - right}" y2="${y.toFixed(1)}" class="chart-grid"/>`);
    parts.push(`<text x="8" y="${(y + 4).toFixed(1)}" class="chart-tick">${Math.round(value)}</text>`);
  });
  keys.forEach((key, keyIndex) => {
    const series = rows
      .map((row, rowIndex) => ({ rowIndex, value: Number(row[key]) }))
      .filter((point) => Number.isFinite(point.value));
    if (!series.length) return;
    const path = series.map((point, index) => {
      const command = index === 0 ? "M" : "L";
      return `${command} ${xFor(point.rowIndex).toFixed(1)} ${yFor(point.value).toFixed(1)}`;
    }).join(" ");
    const color = colors[keyIndex] || "#667085";
    parts.push(`<path d="${path}" fill="none" stroke="${escapeAttr(color)}" stroke-width="2.4"/>`);
    series.forEach((point) => {
      parts.push(`<circle cx="${xFor(point.rowIndex).toFixed(1)}" cy="${yFor(point.value).toFixed(1)}" r="3" fill="${escapeAttr(color)}"/>`);
    });
  });
  const firstDate = rows[0]?.snapshot_date || "";
  const lastDate = rows[rows.length - 1]?.snapshot_date || "";
  parts.push(`<text x="${left}" y="${height - 10}" class="chart-tick">${escapeHtml(firstDate)}</text>`);
  parts.push(`<text x="${width - right - 82}" y="${height - 10}" class="chart-tick">${escapeHtml(lastDate)}</text>`);
  parts.push("</svg>");
  return parts.join("");
}

function renderHistoryTable(history, labels) {
  if (!history.length) {
    elements.historyTable.innerHTML = '<div class="empty-state">履歴がまだありません。</div>';
    return;
  }
  const rows = history.slice().reverse();
  const head = historyTableKeys.map((key) => `<th>${escapeHtml(labels[key] || key)}</th>`).join("");
  const body = rows.map((row) => `
    <tr>
      ${historyTableKeys.map((key) => `<td>${escapeHtml(numberText(row[key] ?? ""))}</td>`).join("")}
    </tr>
  `).join("");
  elements.historyTable.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function applyTarget(target) {
  if (!target) {
    return;
  }
  if (target.view === "metrics") {
    setView("metrics");
    return;
  }
  state.status = target.status !== undefined ? target.status || "" : "pending";
  state.source = target.source || "";
  state.domain = target.domain || "";
  state.actionGroup = target.actionGroup || target.action_group || "";
  state.q = target.q || "";
  elements.searchInput.value = state.q;
  state.activeIndex = 0;
  state.itemsLoaded = false;
  renderInventory();
  setView(target.view || "review");
}

function renderInventory() {
  const totals = state.inventory.totals;
  elements.lastUpdated.textContent = `更新 ${formatDate(state.inventory.generated_at)}`;
  elements.totalCount.textContent = totals.total;
  elements.pendingCount.textContent = totals.pending;
  elements.reviewedCount.textContent = totals.reviewed;
  elements.closedCount.textContent = totals.closed;

  document.querySelectorAll(".metric").forEach((button) => {
    button.classList.toggle("active", button.dataset.status === state.status);
  });

  const actionGroups = Object.entries(state.inventory.action_group_counts || {})
    .sort((a, b) => b[1].pending - a[1].pending || (a[1].label || a[0]).localeCompare(b[1].label || b[0], "ja"));
  elements.actionGroupFilters.replaceChildren(
    actionGroupButton("すべて", "", state.actionGroup === "", sumPending(actionGroups)),
    ...actionGroups.map(([groupId, counts]) => (
      actionGroupButton(counts.label || groupId, groupId, state.actionGroup === groupId, counts.pending)
    )),
  );

  const domains = Object.entries(state.inventory.domain_counts)
    .sort((a, b) => b[1].pending - a[1].pending || a[0].localeCompare(b[0], "ja"));
  elements.domainFilters.replaceChildren(
    filterButton("すべて", "", state.domain === "", sumPending(domains)),
    ...domains.map(([domain, counts]) => filterButton(domain, domain, state.domain === domain, counts.pending)),
  );

  const sourceButtons = state.inventory.sources
    .slice()
    .sort((a, b) => b.pending_count - a.pending_count || a.title.localeCompare(b.title, "ja"))
    .map((source) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "source-button";
      button.classList.toggle("active", state.source === source.id);
      button.dataset.source = source.id;
      button.innerHTML = `
        <span>${escapeHtml(source.title)}<br><small>${escapeHtml(source.domain)}</small></span>
        <span class="badge">${source.pending_count}</span>
      `;
      button.addEventListener("click", () => {
        state.source = state.source === source.id ? "" : source.id;
        state.actionGroup = "";
        state.activeIndex = 0;
        loadItems();
        renderInventory();
      });
      return button;
    });
  elements.sourceList.replaceChildren(...sourceButtons);
}

async function loadStageStatus() {
  state.stageStatus = await api("/api/stage-status");
  renderStageNotice();
}

function renderStageNotice() {
  const status = state.stageStatus;
  if (!status || !status.needs_attention) {
    elements.stageNotice.hidden = true;
    elements.stageNotice.replaceChildren();
    return;
  }
  elements.stageNotice.hidden = false;
  elements.stageNotice.classList.toggle("outdated", Boolean(status.is_outdated));
  const text = document.createElement("div");
  text.innerHTML = `
    <strong>${escapeHtml(status.label)}</strong>
    <p>${escapeHtml(status.message)} ${escapeHtml(String(status.decision_count))}件 / ${escapeHtml(String(status.staged_file_count))}ファイル${status.generated_at ? ` / ステージ ${escapeHtml(formatDate(status.generated_at))}` : ""}</p>
  `;
  const actions = document.createElement("div");
  actions.className = "stage-notice-actions";
  const reviewed = document.createElement("button");
  reviewed.type = "button";
  reviewed.textContent = "決定済みを見る d";
  reviewed.addEventListener("click", () => setStatusFilter("reviewed"));
  actions.append(reviewed);
  if (status.is_outdated) {
    const restage = document.createElement("button");
    restage.type = "button";
    restage.className = "primary";
    restage.textContent = "再ステージ g";
    restage.addEventListener("click", stageCurrentDecisions);
    actions.append(restage);
  } else {
    const ack = document.createElement("button");
    ack.type = "button";
    ack.textContent = "個別apply済みとして記録";
    ack.addEventListener("click", acknowledgeStage);
    actions.append(ack);
  }
  elements.stageNotice.replaceChildren(text, actions);
}

function renderUndoButton() {
  const status = state.undoStatus || {};
  const count = Number(status.undo_count || 0);
  elements.undoButton.disabled = count <= 0;
  elements.undoButton.title = count > 0 ? undoTitle(status.last || {}) : "取り消せる操作はありません";
  elements.undoButton.innerHTML = `元に戻す <kbd>z</kbd>${count > 1 ? ` <span class="undo-count">${count}</span>` : ""}`;
}

function undoTitle(entry) {
  const after = entry.after || {};
  const before = entry.before || {};
  const label = after.apply_value_label || after.decision_label || before.apply_value_label || before.decision_label || entry.action || "";
  return label ? `直前の操作を取り消す: ${label}` : "直前の操作を取り消す";
}

function actionGroupButton(label, value, active, count) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "filter action-filter";
  button.classList.toggle("active", active);
  button.innerHTML = `<span>${escapeHtml(label)}</span><span class="badge">${count}</span>`;
  button.addEventListener("click", () => {
    state.actionGroup = value;
    state.source = "";
    state.domain = "";
    state.activeIndex = 0;
    loadItems();
    renderInventory();
  });
  return button;
}

function filterButton(label, value, active, count) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "filter";
  button.classList.toggle("active", active);
  button.innerHTML = `<span>${escapeHtml(label)}</span><span class="badge">${count}</span>`;
  button.addEventListener("click", () => {
    state.domain = value;
    state.actionGroup = "";
    state.activeIndex = 0;
    loadItems();
    renderInventory();
  });
  return button;
}

function sumPending(domains) {
  return domains.reduce((total, [, counts]) => total + counts.pending, 0);
}

async function loadItems() {
  const params = new URLSearchParams();
  if (state.status) params.set("status", state.status);
  if (state.source) params.set("source", state.source);
  if (state.domain) params.set("domain", state.domain);
  if (state.actionGroup) params.set("action_group", state.actionGroup);
  if (state.q) params.set("q", state.q);
  params.set("limit", state.limit);
  const payload = await api(`/api/items?${params.toString()}`);
  state.itemsLoaded = true;
  renderItems(payload.items, payload.count);
}

function renderItems(items, count) {
  state.currentItems = items;
  const statusText = state.status ? statusLabel(state.status) : "全件";
  const sourceText = state.source ? sourceTitle(state.source) : "";
  const domainText = state.domain || "";
  const actionGroupText = state.actionGroup ? actionGroupTitle(state.actionGroup) : "";
  elements.listTitle.textContent = [statusText, actionGroupText, domainText, sourceText].filter(Boolean).join(" / ");
  elements.listSummary.textContent = `${count}件`;
  elements.items.replaceChildren(...items.map(renderItem));
  setActiveIndex(state.activeIndex, { scroll: false });
}

function renderItem(item) {
  const article = document.createElement("article");
  article.className = `item ${item.status}`;
  article.dataset.itemId = item.id;
  article.dataset.firstUrl = item.urls[0] || "";
  article.dataset.searchTitle = item.title || "";
  const decision = item.console_decision || {};
  article.innerHTML = `
    <div class="item-main">
      <div class="chips">
        <span class="chip ${item.status}">${escapeHtml(item.status_label)}</span>
        ${item.action_group_label ? `<span class="chip action-group">${escapeHtml(item.action_group_label)}</span>` : ""}
        <span class="chip">${escapeHtml(item.source_title)}</span>
        <span class="chip">${escapeHtml(item.domain)}</span>
        ${item.priority_label ? `<span class="chip">${escapeHtml(item.priority_label)}</span>` : ""}
        ${item.score ? `<span class="chip">score ${escapeHtml(item.score)}</span>` : ""}
      </div>
      <div class="item-title-row">
        <h3>${escapeHtml(item.title)}</h3>
        <button
          type="button"
          class="event-search"
          title="イベント名でGoogle検索"
          aria-label="イベント名でGoogle検索"
        >Google検索 <kbd>s</kbd></button>
      </div>
      ${item.subtitle ? `<p class="muted">${escapeHtml(item.subtitle)}</p>` : ""}
      ${item.action_group_reason ? `<p class="muted">次アクション: ${escapeHtml(item.action_group_reason)}</p>` : ""}
      ${item.action ? `<p><strong>${escapeHtml(item.action)}</strong></p>` : ""}
      ${item.description ? `<p class="description">${escapeHtml(item.description)}</p>` : ""}
      ${item.source_decision ? `<p class="muted">既存値: ${escapeHtml(item.source_decision)}</p>` : ""}
      ${comparisonHtml(item.comparison)}
      ${targetEventHtml(item.target_event)}
      ${item.route_note ? `<p class="route-note">${escapeHtml(item.route_note)}</p>` : ""}
      ${researchAdviceHtml(item.research_advice)}
      ${routeChecksHtml(item.route_checks || [], item.route_check_title)}
      <div class="urls">${item.urls.slice(0, 6).map((url, index) => link(url, index === 0 ? "o" : "")).join("")}</div>
      <div class="details">
        ${item.details.slice(0, 10).map((detail) => `
          <div class="detail"><span>${escapeHtml(detail.label)}</span><strong>${escapeHtml(detail.value)}</strong></div>
        `).join("")}
      </div>
    </div>
    <div class="decision-box">
      ${decisionButtonsHtml(item, decision.decision)}
      ${applyOptionsHtml(item, decision.apply_value || "")}
      ${youtubeManualFieldsHtml(item, decision)}
      <textarea class="note" placeholder="メモ (n)">${escapeHtml(decision.note || "")}</textarea>
      <div class="decision-actions">
        <button type="button" class="clear">解除 <kbd>c</kbd></button>
      </div>
      <button type="button" class="raw">JSON詳細 <kbd>i</kbd></button>
    </div>
  `;
  article.querySelectorAll(".decision-buttons button").forEach((button) => {
    button.addEventListener("click", () => {
      saveDecision(article, item.id, {
        decision: button.dataset.decision,
        applyValue: "",
      });
    });
  });
  article.querySelectorAll(".apply-option").forEach((button) => {
    button.addEventListener("click", () => {
      saveDecision(article, item.id, {
        decision: button.dataset.decision,
        applyValue: button.dataset.applyValue,
      });
    });
  });
  article.dataset.decision = decision.decision || "";
  article.dataset.applyValue = decision.apply_value || "";
  article.addEventListener("click", () => {
    const cards = visibleItems();
    const index = cards.indexOf(article);
    if (index >= 0) {
      setActiveIndex(index, { scroll: false });
    }
  });
  article.querySelector(".clear").addEventListener("click", () => clearDecision(item.id));
  article.querySelector(".raw").addEventListener("click", () => showRaw(item.id, item.title));
  article.querySelector(".target-event-detail")?.addEventListener("click", () => showTargetEvent(item));
  article.querySelector(".event-search").addEventListener("click", () => openGoogleSearch(item.title));
  return article;
}

function comparisonHtml(comparison) {
  if (!comparison || (!comparison.candidate && !comparison.target)) return "";
  return `
    <section class="comparison" aria-label="${escapeAttr(comparison.title || "比較対象")}">
      <div class="comparison-head">
        <strong>${escapeHtml(comparison.title || "比較対象")}</strong>
        ${comparison.question ? `<span>${escapeHtml(comparison.question)}</span>` : ""}
      </div>
      <div class="comparison-grid">
        ${comparisonSideHtml(comparison.candidate)}
        <div class="comparison-arrow" aria-hidden="true">→</div>
        ${comparisonSideHtml(comparison.target)}
      </div>
      ${comparison.evidence?.length ? `
        <div class="comparison-evidence">
          ${comparison.evidence.map((text) => `<span>${escapeHtml(text)}</span>`).join("")}
        </div>
      ` : ""}
    </section>
  `;
}

function comparisonSideHtml(side) {
  if (!side) return `<div class="comparison-side empty"><span>未特定</span></div>`;
  return `
    <div class="comparison-side">
      <span>${escapeHtml(side.label || "")}</span>
      <strong>${escapeHtml(side.name || "名称未設定")}</strong>
      ${(side.meta || []).map((text) => `<small>${escapeHtml(text)}</small>`).join("")}
    </div>
  `;
}

function targetEventHtml(target) {
  if (!target || !target.name) return "";
  const meta = [target.date, target.venue, target.area].filter(Boolean).join(" / ");
  return `
    <div class="target-event">
      <div>
        <span>追加先イベント</span>
        <strong>${escapeHtml(target.name)}</strong>
        ${meta ? `<small>${escapeHtml(meta)}</small>` : ""}
      </div>
      <button type="button" class="target-event-detail">詳細</button>
    </div>
  `;
}

function routeChecksHtml(checks, title = "採用後に残る情報") {
  if (!checks.length) return "";
  return `
    <div class="route-checks">
      <p>${escapeHtml(title || "採用後に残る情報")}</p>
      <div>
        ${checks.map((check) => `
          <span class="route-check ${escapeAttr(check.kind || "warn")}" title="${escapeAttr(check.message || "")}">
            <strong>${escapeHtml(check.label || "")}</strong>
            <em>${escapeHtml(check.value || "")}</em>
            ${check.message ? `<small>${escapeHtml(check.message)}</small>` : ""}
          </span>
        `).join("")}
      </div>
    </div>
  `;
}

function researchAdviceHtml(advice) {
  if (!advice || !advice.status) return "";
  return `
    <p class="route-note">
      調査アドバイス: <strong>${escapeHtml(advice.status)}</strong>
      ${advice.message ? ` / ${escapeHtml(advice.message)}` : ""}
    </p>
  `;
}

function youtubeManualFieldsHtml(item, decision) {
  if (item.source_id !== "youtube_active_video") return "";
  const targetValue = decision.manual_target_event_name || item.target_event?.name || item.title_event_name_candidate || "";
  const songValues = Array.isArray(decision.manual_song_names) && decision.manual_song_names.length
    ? decision.manual_song_names
    : item.song_candidates || [];
  return `
    <div class="manual-fields">
      <label>
        <span>追加先イベント名</span>
        <input
          class="target-event-name"
          type="text"
          value="${escapeAttr(targetValue)}"
          placeholder="例: みたままつり 納涼民踊のつどい"
        >
      </label>
      <label>
        <span>曲名</span>
        <input
          class="target-song-names"
          type="text"
          value="${escapeAttr(songValues.join(", "))}"
          placeholder="例: ダンシングヒーロー"
        >
      </label>
    </div>
  `;
}

function applyOptionsHtml(item, selectedValue) {
  const options = item.apply_options || [];
  if (!options.length) return "";
  const heading = item.source_id === "x_candidate_post"
    ? "情報源判断（押すと保存）"
    : "この判断で変わるもの（押すと保存）";
  return `
    <div class="apply-options">
      <p>${escapeHtml(heading)}</p>
      ${options.map((option, index) => `
        <button
          type="button"
          class="apply-option ${selectedValue === option.value ? "selected" : ""}"
          data-apply-value="${escapeAttr(option.value)}"
          data-decision="${escapeAttr(option.decision || "accept")}"
          data-shortcut="${index + 1}"
          data-original-disabled="${option.disabled ? "true" : "false"}"
          title="${escapeAttr(option.disabled_reason || option.help || option.value)}"
          ${option.disabled ? "disabled" : ""}
        >
          <span>${escapeHtml(option.label || option.value)}${index < 5 ? ` <kbd>${index + 1}</kbd>` : ""}</span>
          ${option.disabled_reason ? `<small>${escapeHtml(option.disabled_reason)}</small>` : option.help ? `<small>${escapeHtml(option.help)}</small>` : ""}
        </button>
      `).join("")}
    </div>
  `;
}

function decisionButtonsHtml(item, selected) {
  if ((item.apply_options || []).length) return "";
  return `
    <div class="decision-buttons">
      ${decisionButton("accept", selected, 1)}
      ${decisionButton("reject", selected, 2)}
      ${decisionButton("hold", selected, 3)}
      ${decisionButton("needs_research", selected, 4)}
    </div>
  `;
}

function decisionButton(value, selected, shortcut) {
  return `<button type="button" data-decision="${value}" data-shortcut="${shortcut}" class="${selected === value ? "selected" : ""}">${labels[value]} <kbd>${shortcut}</kbd></button>`;
}

async function saveDecision(article, itemId, values = {}) {
  if (state.savingItemIds.has(itemId)) {
    showMessage("保存中です");
    return;
  }
  const decision = values.decision || article.dataset.decision;
  if (!decision) {
    showMessage("判断ボタンを選んでください");
    return;
  }
  const applyValue = values.applyValue ?? article.dataset.applyValue ?? "";
  state.savingItemIds.add(itemId);
  setDecisionBoxDisabled(article, true);
  try {
    await api("/api/decision", {
      method: "POST",
      body: JSON.stringify({
        item_id: itemId,
        decision,
        note: article.querySelector(".note").value,
        apply_value: applyValue,
        target_event_name: article.querySelector(".target-event-name")?.value || "",
        target_song_names: article.querySelector(".target-song-names")?.value || "",
      }),
    });
  } catch (error) {
    showMessage(error.message);
    setDecisionBoxDisabled(article, false);
    state.savingItemIds.delete(itemId);
    return;
  }
  showMessage("保存しました");
  state.savingItemIds.delete(itemId);
  await refreshCurrentView();
}

function setDecisionBoxDisabled(article, disabled) {
  article.querySelectorAll(".decision-buttons button, .apply-option, .clear").forEach((button) => {
    button.disabled = disabled || button.dataset.originalDisabled === "true";
  });
}

async function clearDecision(itemId) {
  await api("/api/decision", {
    method: "POST",
    body: JSON.stringify({ item_id: itemId, decision: "clear" }),
  });
  showMessage("解除しました");
  await refreshCurrentView();
}

async function undoLastDecision() {
  const result = await api("/api/undo", {
    method: "POST",
    body: "{}",
  });
  showMessage(`元に戻しました: ${shortItemId(result.item_id || "")}`);
  await refreshCurrentView();
}

async function showRaw(itemId, title) {
  const detail = await api(`/api/item/${encodeURIComponent(itemId)}`);
  elements.detailTitle.textContent = title;
  elements.detailRaw.textContent = JSON.stringify(detail.raw || detail, null, 2);
  elements.detailDialog.showModal();
}

function showHelp() {
  elements.helpDialog.showModal();
}

function showTargetEvent(item) {
  const target = item.target_event;
  if (!target) {
    showMessage("追加先イベントは未特定です");
    return;
  }
  elements.detailTitle.textContent = `追加先イベント: ${target.name}`;
  elements.detailRaw.textContent = JSON.stringify(target, null, 2);
  elements.detailDialog.showModal();
}

function link(url, shortcut = "") {
  const shortcutHtml = shortcut ? `<kbd>${escapeHtml(shortcut)}</kbd>` : "";
  return `<a href="${escapeAttr(url)}" target="_blank" rel="noreferrer">${escapeHtml(shortUrl(url))}${shortcutHtml}</a>`;
}

function shortUrl(url) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname}`.slice(0, 72);
  } catch {
    return url.slice(0, 72);
  }
}

function shortItemId(itemId) {
  const text = String(itemId || "");
  if (!text) return "直前の操作";
  const [, key = text] = text.split(/:(.*)/s);
  return key.length > 42 ? `${key.slice(0, 42)}...` : key;
}

function sourceTitle(sourceId) {
  const source = state.inventory.sources.find((item) => item.id === sourceId);
  return source ? source.title : sourceId;
}

function actionGroupTitle(groupId) {
  const group = state.inventory?.action_group_counts?.[groupId];
  return group ? group.label : groupId;
}

function statusLabel(status) {
  return {
    pending: "未レビュー",
    reviewed: "決定済み",
    closed: "処理済み",
  }[status] || "全件";
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ja-JP", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(date);
}

function numberText(value) {
  if (value === null || value === undefined || value === "") return "0";
  if (typeof value === "number" && Number.isFinite(value)) {
    return new Intl.NumberFormat("ja-JP").format(value);
  }
  const parsed = Number(value);
  if (Number.isFinite(parsed) && String(value).trim() !== "") {
    return new Intl.NumberFormat("ja-JP").format(parsed);
  }
  return String(value);
}

function deltaText(delta) {
  if (delta === null || delta === undefined) return "前回差分なし";
  if (delta > 0) return `前回 +${numberText(delta)}`;
  if (delta < 0) return `前回 ${numberText(delta)}`;
  return "前回 0";
}

function deltaClass(delta, kind) {
  if (delta === null || delta === undefined || delta === 0) return "flat";
  if (kind === "less_is_good") return delta < 0 ? "good" : "warn";
  if (kind === "more_can_be_noise") return delta > 0 ? "warn" : "good";
  if (kind === "more_needs_review") return delta > 0 ? "warn" : "good";
  if (kind === "more_can_be_good") return delta > 0 ? "good" : "flat";
  return delta > 0 ? "up" : "down";
}

function attentionValueText(value) {
  if (value === null || value === undefined || value === "") return "";
  const parsed = Number(value);
  if (Number.isFinite(parsed) && String(value).trim() !== "") {
    return `${numberText(value)}件`;
  }
  return numberText(value);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("\n", " ");
}

function visibleItems() {
  return Array.from(elements.items.querySelectorAll(".item"));
}

function activeItem() {
  return visibleItems()[state.activeIndex] || null;
}

function setActiveIndex(index, options = {}) {
  const cards = visibleItems();
  cards.forEach((card) => card.classList.remove("active"));
  if (!cards.length) {
    state.activeIndex = 0;
    return null;
  }
  state.activeIndex = Math.max(0, Math.min(index, cards.length - 1));
  const card = cards[state.activeIndex];
  card.classList.add("active");
  if (options.scroll !== false) {
    card.scrollIntoView({ block: "center", behavior: options.smooth === false ? "auto" : "smooth" });
  }
  return card;
}

function moveActive(delta) {
  setActiveIndex(state.activeIndex + delta);
}

function activateDecisionShortcut(shortcut) {
  const card = activeItem();
  if (!card) return;
  const button = card.querySelector(`[data-shortcut="${shortcut}"]`);
  if (!button) {
    showMessage(`${shortcut}番の判断ボタンはありません`);
    return;
  }
  if (button.disabled) {
    showMessage(button.title || "この判断は選べません");
    return;
  }
  button.click();
}

function focusActive(selector) {
  const card = activeItem();
  const target = card && card.querySelector(selector);
  if (target) {
    target.focus();
  }
}

function openActiveUrl() {
  const card = activeItem();
  const url = card && card.dataset.firstUrl;
  if (url) {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

function googleSearchUrl(query) {
  return `https://www.google.com/search?q=${encodeURIComponent(query || "")}`;
}

function openGoogleSearch(query) {
  if (!query) return;
  window.open(googleSearchUrl(query), "_blank", "noopener,noreferrer");
}

function openActiveGoogleSearch() {
  const card = activeItem();
  const title = card && card.dataset.searchTitle;
  if (title) {
    openGoogleSearch(title);
  }
}

function setStatusFilter(status) {
  state.status = status;
  state.activeIndex = 0;
  state.itemsLoaded = false;
  renderInventory();
  setView("review");
}

async function exportCurrentDecisions() {
  const result = await api("/api/export", { method: "POST", body: "{}" });
  showMessage(`判断をまとめました: ${result.path}`);
}

async function writeCurrentInventory() {
  const result = await api("/api/inventory/write", { method: "POST", body: "{}" });
  showMessage(`棚卸しを保存しました: ${result.markdown_path}`);
}

async function stageCurrentDecisions() {
  const result = await api("/api/stage-apply", { method: "POST", body: "{}" });
  showMessage(`反映準備ファイルを作りました: ${result.decision_count}件`);
  await loadStageStatus();
  await loadAdminSummary();
}

async function acknowledgeStage() {
  const ok = window.confirm("個別applyをdry-run後に明示実行済みの場合だけ記録します。よろしいですか？");
  if (!ok) return;
  await api("/api/stage-ack", {
    method: "POST",
    body: JSON.stringify({ acknowledged_by: "内田さん" }),
  });
  showMessage("個別apply済みとして記録しました");
  await loadStageStatus();
  await loadAdminSummary();
}

function isTextInput(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

function handleTextInputKey(event) {
  if (event.key === "Escape") {
    event.target.blur();
    setActiveIndex(state.activeIndex, { scroll: false });
  }
}

async function handleGlobalKeydown(event) {
  if (elements.detailDialog.open || elements.helpDialog.open) {
    if (event.key === "Escape") {
      if (elements.detailDialog.open) elements.detailDialog.close();
      if (elements.helpDialog.open) elements.helpDialog.close();
    }
    return;
  }
  if (isTextInput(event.target)) {
    handleTextInputKey(event);
    return;
  }
  if (event.metaKey || event.ctrlKey || event.altKey) {
    return;
  }
  const key = shortcutKey(event);
  const sharedActions = {
    r: refreshCurrentView,
    "?": showHelp,
    h: () => setView("home"),
    q: () => setView("collection"),
    m: () => setView("metrics"),
    v: () => setView("review"),
    a: () => setStatusFilter(""),
    u: () => setStatusFilter("pending"),
    d: () => setStatusFilter("reviewed"),
    p: () => setStatusFilter("closed"),
    z: undoLastDecision,
  };
  const reviewActions = {
    j: () => moveActive(1),
    ArrowDown: () => moveActive(1),
    k: () => moveActive(-1),
    ArrowUp: () => moveActive(-1),
    "1": () => activateDecisionShortcut(1),
    "2": () => activateDecisionShortcut(2),
    "3": () => activateDecisionShortcut(3),
    "4": () => activateDecisionShortcut(4),
    "5": () => activateDecisionShortcut(5),
    c: () => {
      const card = activeItem();
      if (card) return clearDecision(card.dataset.itemId);
    },
    n: () => focusActive(".note"),
    y: () => focusActive(".target-event-name"),
    x: () => focusActive(".target-song-names"),
    i: () => {
      const card = activeItem();
      const title = card && card.querySelector("h3")?.textContent;
      if (card) return showRaw(card.dataset.itemId, title || "詳細");
    },
    o: openActiveUrl,
    s: openActiveGoogleSearch,
    "/": () => elements.searchInput.focus(),
    e: exportCurrentDecisions,
    t: writeCurrentInventory,
    g: stageCurrentDecisions,
    Escape: () => setActiveIndex(state.activeIndex),
  };
  const actions = state.view === "review" ? { ...sharedActions, ...reviewActions } : sharedActions;
  const action = actions[key];
  if (!action) return;
  event.preventDefault();
  try {
    await action();
  } catch (error) {
    showMessage(error.message);
    console.error(error);
  }
}

document.querySelectorAll(".metric").forEach((button) => {
  button.addEventListener("click", () => {
    setStatusFilter(button.dataset.status);
  });
});

elements.viewTabs.forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});
document.querySelectorAll(".stat-card").forEach((button) => {
  button.addEventListener("click", () => applyTarget({
    view: button.dataset.targetView || "review",
    status: button.dataset.targetStatus || "pending",
    source: button.dataset.targetSource || "",
    domain: button.dataset.targetDomain || "",
    actionGroup: button.dataset.targetActionGroup || "",
  }));
});
elements.openPendingButton.addEventListener("click", () => applyTarget({ view: "review", status: "pending" }));
elements.reloadCollectionButton.addEventListener("click", loadCollectionStatus);
elements.openMetricsReviewButton.addEventListener("click", () => applyTarget({ view: "review", status: "pending" }));
document.querySelector("#refreshButton").addEventListener("click", refreshCurrentView);
document.querySelector("#helpButton").addEventListener("click", showHelp);
document.querySelector("#helpInlineButton").addEventListener("click", showHelp);
elements.undoButton.addEventListener("click", undoLastDecision);
document.querySelector("#exportButton").addEventListener("click", exportCurrentDecisions);
document.querySelector("#inventoryButton").addEventListener("click", writeCurrentInventory);
document.querySelector("#stageButton").addEventListener("click", stageCurrentDecisions);
document.querySelector("#closeDialog").addEventListener("click", () => elements.detailDialog.close());
document.querySelector("#closeHelpDialog").addEventListener("click", () => elements.helpDialog.close());
elements.searchInput.addEventListener("input", debounce(() => {
  state.q = elements.searchInput.value.trim();
  state.activeIndex = 0;
  loadItems();
}, 250));
elements.limitSelect.addEventListener("change", () => {
  state.limit = elements.limitSelect.value;
  state.activeIndex = 0;
  loadItems();
});
document.addEventListener("keydown", handleGlobalKeydown);

function shortcutKey(event) {
  return event.key.length === 1 ? event.key.toLowerCase() : event.key;
}

function debounce(fn, wait) {
  let timer = 0;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), wait);
  };
}

async function boot() {
  await loadInventory({ refreshItems: false });
  await loadUndoStatus();
  await loadAdminSummary();
  setView("home");
}

boot().catch((error) => {
  showMessage(error.message);
  console.error(error);
});
