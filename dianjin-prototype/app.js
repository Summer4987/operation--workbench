(function () {
  const rules = window.DIANJIN_RULES;
  const logic = window.DIANJIN_LOGIC;

  const els = {
    taskCount: document.querySelector("#taskCount"),
    periodFilter: document.querySelector("#periodFilter"),
    timeFilter: document.querySelector("#timeFilter"),
    storeFilter: document.querySelector("#storeFilter"),
    typeFilter: document.querySelector("#typeFilter"),
    statusFilter: document.querySelector("#statusFilter"),
    taskList: document.querySelector("#taskList"),
    progressText: document.querySelector("#progressText"),
    selectedType: document.querySelector("#selectedType"),
    taskDetail: document.querySelector("#taskDetail"),
    taskActions: document.querySelector("#taskActions"),
    automationPreview: document.querySelector("#automationPreview"),
    markDone: document.querySelector("#markDone"),
    markSkipped: document.querySelector("#markSkipped"),
    markPending: document.querySelector("#markPending"),
    simulator: document.querySelector("#simulator"),
    actualSpend: document.querySelector("#actualSpend"),
    calculateBtn: document.querySelector("#calculateBtn"),
    calcResult: document.querySelector("#calcResult"),
    actionLog: document.querySelector("#actionLog"),
    resetLog: document.querySelector("#resetLog"),
    showNextTask: document.querySelector("#showNextTask"),
    exportLog: document.querySelector("#exportLog"),
  };

  const storageKey = "dianjin-prototype-run-v1";
  let selectedTaskId = "";
  let runState = loadRunState();

  const tasks = logic.buildTasks(rules);
  const backendState = window.DIANJIN_CURRENT_STATE || null;
  const executionPreview = window.DIANJIN_EXECUTION_PREVIEW || null;
  const backendByTaskId = new Map((backendState?.recommendations || []).map((item) => [item.task.id, item]));
  const previewByTaskId = new Map((executionPreview?.rows || []).map((item) => [item.taskId, item]));

  function fillFilters() {
    const times = Array.from(new Set(tasks.map((task) => task.time))).sort((a, b) => logic.timeValue(a) - logic.timeValue(b));
    for (const time of times) {
      const option = document.createElement("option");
      option.value = time;
      option.textContent = time;
      els.timeFilter.appendChild(option);
    }

    for (const store of rules.stores) {
      const option = document.createElement("option");
      option.value = store.name;
      option.textContent = store.name;
      els.storeFilter.appendChild(option);
    }
  }

  function filteredTasks() {
    return tasks.filter((task) => {
      const periodOk = els.periodFilter.value === "all" || task.period === els.periodFilter.value;
      const timeOk = els.timeFilter.value === "all" || task.time === els.timeFilter.value;
      const storeOk = els.storeFilter.value === "all" || task.store === els.storeFilter.value;
      const typeOk = els.typeFilter.value === "all" || task.type === els.typeFilter.value;
      const statusOk = els.statusFilter.value === "all" || getTaskStatus(task.id) === els.statusFilter.value;
      return periodOk && timeOk && storeOk && typeOk && statusOk;
    });
  }

  function renderTasks() {
    const visible = filteredTasks();
    els.taskCount.textContent = String(visible.length);
    renderProgress();
    els.taskList.innerHTML = "";

    if (!visible.length) {
      els.taskList.innerHTML = '<div class="empty-state">没有符合条件的任务。</div>';
      return;
    }

    for (const task of visible) {
      const button = document.createElement("button");
      button.type = "button";
      const status = getTaskStatus(task.id);
      button.className = `task-card ${task.id === selectedTaskId ? "selected" : ""} status-${status}`;
      button.innerHTML = `
        <span class="task-time">${task.time}</span>
        <span class="task-main">
          <strong>${task.store}</strong>
          <small>${task.period} · ${task.typeLabel} · ${previewLabel(task) || task.summary}</small>
        </span>
        <span class="task-status">${statusLabel(status)}</span>
      `;
      button.addEventListener("click", () => selectTask(task.id));
      els.taskList.appendChild(button);
    }
  }

  function selectTask(taskId) {
    selectedTaskId = taskId;
    const task = tasks.find((item) => item.id === taskId);
    if (!task) return;

    els.selectedType.textContent = task.typeLabel;
    els.taskDetail.classList.remove("empty-state");
    els.taskDetail.innerHTML = task.type === "budget" ? renderBudgetDetail(task) : renderCheckDetail(task);
    els.automationPreview.classList.remove("hidden");
    els.automationPreview.innerHTML = renderAutomationPreview(task);
    els.taskActions.classList.remove("hidden");
    els.simulator.classList.toggle("hidden", task.type !== "bid-check");
    els.actualSpend.value = "";
    els.calcResult.innerHTML = "";
    renderTasks();
  }

  function renderBudgetDetail(task) {
    return `
      <dl>
        <div><dt>平台</dt><dd>${task.platform}</dd></div>
        <div><dt>时段</dt><dd>${task.period}</dd></div>
        <div><dt>执行时间</dt><dd>${task.time}</dd></div>
        <div><dt>门店</dt><dd>${task.store}</dd></div>
        <div><dt>饿了么ID</dt><dd>${task.shopId || "未匹配"}</dd></div>
        <div><dt>预算动作</dt><dd>调整为 ${task.budget} 元</dd></div>
        <div><dt>出价动作</dt><dd>${task.bidAction}</dd></div>
        ${renderBackendStateRows(task)}
        <div><dt>任务状态</dt><dd>${statusLabel(getTaskStatus(task.id))}</dd></div>
      </dl>
    `;
  }

  function renderCheckDetail(task) {
    return `
      <dl>
        <div><dt>平台</dt><dd>${task.platform}</dd></div>
        <div><dt>检查时间</dt><dd>${task.time}</dd></div>
        <div><dt>门店</dt><dd>${task.store}</dd></div>
        <div><dt>饿了么ID</dt><dd>${task.shopId || "未匹配"}</dd></div>
        <div><dt>午餐初始预算</dt><dd>${task.budget} 元</dd></div>
        <div><dt>本时间点预期消耗</dt><dd>${task.expectedSpend} 元</dd></div>
        <div><dt>判断规则</dt><dd>低于预期 +0.1；超出10%到20%之间 -0.1；超出20%或以上 -0.2。</dd></div>
        ${renderBackendStateRows(task)}
        <div><dt>任务状态</dt><dd>${statusLabel(getTaskStatus(task.id))}</dd></div>
      </dl>
    `;
  }

  function renderBackendStateRows(task) {
    const state = backendByTaskId.get(task.id);
    if (!state) {
      return `
        <div><dt>后台状态</dt><dd>暂无读取结果</dd></div>
        ${renderExecutionPreviewRows(task)}
      `;
    }
    if (!state.found) {
      return `<div><dt>后台状态</dt><dd>${state.recommendation}</dd></div>`;
    }
    const current = state.current || {};
    const pieces = [
      `当前出价 ${current.bid ?? "-"}`,
      `预算 ${current.budget ?? "-"}`,
      `今日花费 ${current.spend ?? "-"}`,
      `使用率 ${current.budgetUsage || "-"}`,
    ];
    return `
      <div><dt>后台状态</dt><dd>${pieces.join(" · ")}</dd></div>
      <div><dt>后台建议</dt><dd>${state.recommendation}</dd></div>
      ${renderExecutionPreviewRows(task)}
    `;
  }

  function renderExecutionPreviewRows(task) {
    const preview = previewByTaskId.get(task.id);
    if (!preview) {
      return '<div><dt>执行预览</dt><dd>暂无执行预览</dd></div>';
    }
    const actionClass = preview.canExecute ? "preview-ok" : "preview-blocked";
    const values =
      task.type === "budget"
        ? `当前预算 ${moneyText(preview.currentBudget)}，目标预算 ${moneyText(preview.targetBudget)}`
        : `当前出价 ${moneyText(preview.currentBid)}，目标出价 ${moneyText(preview.targetBid)}，最低出价 ${moneyText(preview.minBid)}，今日花费 ${moneyText(preview.currentSpend)}，预期 ${moneyText(preview.expectedSpend)}`;
    const risk = preview.risk ? `<span class="preview-risk">${preview.risk}</span>` : "";
    return `
      <div><dt>执行预览</dt><dd><span class="${actionClass}">${preview.action}</span>${risk}</dd></div>
      <div><dt>目标结果</dt><dd>${values}</dd></div>
    `;
  }

  function previewLabel(task) {
    const preview = previewByTaskId.get(task.id);
    if (!preview) return "";
    if (task.type === "budget") {
      return `${preview.action} · 当前预算 ${moneyText(preview.currentBudget)}`;
    }
    return `${preview.action} · ${moneyText(preview.currentBid)} -> ${moneyText(preview.targetBid)}`;
  }

  function renderAutomationPreview(task) {
    const preview = previewByTaskId.get(task.id);
    const action =
      preview
        ? `按执行预览处理：${preview.action}${task.type === "bid-check" ? `，目标出价 ${moneyText(preview.targetBid)}` : `，目标预算 ${moneyText(preview.targetBudget)}`}。`
        : task.type === "budget"
        ? `切换到当前门店，将预算调整为 ${task.budget} 元，出价保持不变。`
        : `读取实际使用金额，对比预期 ${task.expectedSpend} 元，再按规则调整出价。`;
    return `
      <h2>后台动作预案</h2>
      <ol>
        <li>打开饿了么点金推广页面。</li>
        <li>确认或切换到「${task.store}」。</li>
        <li>${action}</li>
        <li>保存前再次校验门店名称，并记录截图和日志。</li>
      </ol>
    `;
  }

  function renderResult(result, task, actual) {
    els.calcResult.className = `calc-result ${result.className}`;
    els.calcResult.innerHTML = `
      <strong>${result.label}</strong>
      <span>${result.reason}</span>
    `;
    if (!Number.isFinite(actual) || actual < 0) {
      return;
    }
    setTaskStatus(task.id, "done");
    addLog({
      event: "消耗检查",
      store: task.store,
      period: task.period,
      checkTime: task.time,
      expected: task.expectedSpend,
      actual,
      action: result.label,
      status: "已完成",
      note: result.reason,
    });
    selectTask(task.id);
  }

  function renderLog() {
    const logs = runState.logs;
    if (!logs.length) {
      els.actionLog.textContent = "暂无记录";
      return;
    }
    els.actionLog.innerHTML = logs
      .map(
        (log) => `
          <div class="log-row">
            <span>${log.time}</span>
            <strong>${log.store}</strong>
            <span>${log.checkTime} · ${log.event} · ${formatLogNumbers(log)}</span>
            <em>${log.action}</em>
          </div>
        `
      )
      .join("");
  }

  function renderProgress() {
    const counts = tasks.reduce(
      (memo, task) => {
        memo[getTaskStatus(task.id)] += 1;
        return memo;
      },
      { pending: 0, done: 0, skipped: 0 }
    );
    const previewText = executionPreview
      ? ` · 预览 ${executionPreview.summary.executable}/${executionPreview.summary.total} 可执行`
      : "";
    els.progressText.textContent = `未执行 ${counts.pending} · 已完成 ${counts.done} · 已跳过 ${counts.skipped}${previewText}`;
  }

  function bindEvents() {
    for (const filter of [els.periodFilter, els.timeFilter, els.storeFilter, els.typeFilter, els.statusFilter]) {
      filter.addEventListener("change", renderTasks);
    }

    els.calculateBtn.addEventListener("click", () => {
      const task = tasks.find((item) => item.id === selectedTaskId);
      if (!task || task.type !== "bid-check") return;
      const actual = els.actualSpend.value.trim() === "" ? Number.NaN : Number(els.actualSpend.value);
      const result = logic.evaluateBid(task.expectedSpend, actual);
      renderResult(result, task, actual);
    });

    els.actualSpend.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        els.calculateBtn.click();
      }
    });

    els.resetLog.addEventListener("click", () => {
      if (!confirm("确定清空当前状态和日志吗？")) return;
      runState = { statuses: {}, logs: [] };
      saveRunState();
      renderTasks();
      renderLog();
      if (selectedTaskId) selectTask(selectedTaskId);
    });

    els.markDone.addEventListener("click", () => {
      const task = getSelectedTask();
      if (!task) return;
      setTaskStatus(task.id, "done");
      addLog(logFromTask(task, "手动记录", "已完成", task.type === "budget" ? `预算调整为 ${task.budget} 元` : "已确认完成"));
      selectTask(task.id);
    });

    els.markSkipped.addEventListener("click", () => {
      const task = getSelectedTask();
      if (!task) return;
      setTaskStatus(task.id, "skipped");
      addLog(logFromTask(task, "跳过任务", "已跳过", "人工跳过"));
      selectTask(task.id);
    });

    els.markPending.addEventListener("click", () => {
      const task = getSelectedTask();
      if (!task) return;
      setTaskStatus(task.id, "pending");
      addLog(logFromTask(task, "恢复任务", "未执行", "恢复为未执行"));
      selectTask(task.id);
    });

    els.showNextTask.addEventListener("click", () => {
      const next = filteredTasks().find((task) => getTaskStatus(task.id) === "pending") || tasks.find((task) => getTaskStatus(task.id) === "pending");
      if (!next) return;
      selectTask(next.id);
    });

    els.exportLog.addEventListener("click", () => {
      exportLogs();
    });
  }

  function getSelectedTask() {
    return tasks.find((item) => item.id === selectedTaskId);
  }

  function getTaskStatus(taskId) {
    return runState.statuses[taskId] || "pending";
  }

  function setTaskStatus(taskId, status) {
    if (status === "pending") {
      delete runState.statuses[taskId];
    } else {
      runState.statuses[taskId] = status;
    }
    saveRunState();
  }

  function statusLabel(status) {
    return { pending: "未执行", done: "已完成", skipped: "已跳过" }[status] || "未执行";
  }

  function addLog(entry) {
    runState.logs.unshift({
      time: new Date().toLocaleString("zh-CN", { hour12: false }),
      ...entry,
    });
    saveRunState();
    renderLog();
    renderTasks();
  }

  function logFromTask(task, event, status, note) {
    return {
      event,
      store: task.store,
      period: task.period,
      checkTime: task.time,
      expected: task.expectedSpend ?? "",
      actual: "",
      action: task.type === "budget" ? `预算 ${task.budget} 元` : "人工确认",
      status,
      note,
    };
  }

  function formatLogNumbers(log) {
    if (log.expected === "" || log.expected === undefined) return log.note || "";
    return `预期 ${log.expected} / 实际 ${logic.formatMoney(log.actual)}`;
  }

  function moneyText(value) {
    return value === undefined || value === null || value === "" ? "-" : `${value} 元`;
  }

  function loadRunState() {
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey) || "");
      return {
        statuses: parsed.statuses || {},
        logs: Array.isArray(parsed.logs) ? parsed.logs : [],
      };
    } catch {
      return { statuses: {}, logs: [] };
    }
  }

  function saveRunState() {
    localStorage.setItem(storageKey, JSON.stringify(runState));
  }

  function exportLogs() {
    const rows = [
      ["记录时间", "事件", "门店", "时段", "任务时间", "预期消耗", "实际消耗", "动作", "状态", "备注"],
      ...runState.logs.map((log) => [
        log.time,
        log.event,
        log.store,
        log.period,
        log.checkTime,
        log.expected,
        log.actual,
        log.action,
        log.status,
        log.note,
      ]),
    ];
    const csv = rows.map((row) => row.map(csvCell).join(",")).join("\n");
    const blob = new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `点金推广模拟日志_${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function csvCell(value) {
    const text = value === undefined || value === null ? "" : String(value);
    return `"${text.replace(/"/g, '""')}"`;
  }

  fillFilters();
  bindEvents();
  selectedTaskId = tasks[0]?.id ?? "";
  renderTasks();
  renderLog();
  if (selectedTaskId) selectTask(selectedTaskId);
})();
