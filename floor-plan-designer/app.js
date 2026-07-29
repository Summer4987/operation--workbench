(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const STORAGE_KEY = "xiongxiaoxiao-floor-plan-v2";
  const LEGACY_STORAGE_KEY = "xiongxiaoxiao-floor-plan-v1";
  const MODELS = [
    { name: "普通操作台", width: 120, height: 60, color: "#60758a", abbr: "台" },
    { name: "冷藏操作台", width: 150, height: 75, color: "#2f7e8d", abbr: "冷" },
    { name: "冷冻操作台", width: 150, height: 75, color: "#3e5d91", abbr: "冻" },
    { name: "货架", width: 120, height: 50, color: "#9a6d3a", abbr: "架" },
    { name: "烤箱", width: 80, height: 80, color: "#a9514b", abbr: "箱" },
    { name: "烤炉", width: 120, height: 80, color: "#b06036", abbr: "炉" },
    { name: "电磁炉", width: 60, height: 60, color: "#4c5564", abbr: "磁" },
    { name: "水池", width: 100, height: 60, color: "#2580a7", abbr: "池" },
    { name: "四门冰箱", width: 120, height: 75, color: "#47728a", abbr: "冰" },
    { name: "保温柜", width: 120, height: 70, color: "#9a6638", abbr: "温" },
    { name: "柱子", width: 40, height: 40, color: "#5b6470", abbr: "柱" },
    { name: "门", width: 90, height: 90, color: "#a87337", abbr: "门", kind: "door" }
  ];

  const $ = (id) => document.getElementById(id);
  const els = {
    roomWidth: $("roomWidthInput"),
    roomHeight: $("roomHeightInput"),
    roomType: $("roomTypeInput"),
    bottomWidth: $("bottomWidthInput"),
    rightDepth: $("rightDepthInput"),
    roomAlignment: $("roomAlignmentInput"),
    shapeFields: $("shapeFields"),
    topWidthLabel: $("topWidthLabel"),
    leftDepthLabel: $("leftDepthLabel"),
    itemWidth: $("itemWidthInput"),
    itemHeight: $("itemHeightInput"),
    gridSize: $("gridSizeInput"),
    updateRoom: $("updateRoomButton"),
    modelList: $("modelList"),
    viewport: $("canvasViewport"),
    svg: $("planCanvas"),
    scene: $("scene"),
    gridBackground: $("gridBackground"),
    roomClipPolygon: $("roomClipPolygon"),
    minorGrid: $("minorGrid"),
    minorGridPath: $("minorGridPath"),
    majorGrid: $("majorGrid"),
    majorGridPath: $("majorGridPath"),
    majorGridMinorFill: $("majorGridMinorFill"),
    meterGrid: $("meterGrid"),
    meterGridPath: $("meterGridPath"),
    meterGridMajorFill: $("meterGridMajorFill"),
    roomLayer: $("roomLayer"),
    guideLayer: $("guideLayer"),
    itemLayer: $("itemLayer"),
    emptyHint: $("emptyHint"),
    undo: $("undoButton"),
    redo: $("redoButton"),
    addText: $("addTextButton"),
    addArrow: $("addArrowButton"),
    duplicate: $("duplicateButton"),
    rotate: $("rotateButton"),
    delete: $("deleteButton"),
    zoomOut: $("zoomOutButton"),
    zoomIn: $("zoomInButton"),
    zoomLabel: $("zoomLabel"),
    fit: $("fitButton"),
    selectionHint: $("selectionHint"),
    noSelection: $("noSelection"),
    propertyForm: $("propertyForm"),
    selectedNameField: $("selectedNameField"),
    selectedNameLabel: $("selectedNameLabel"),
    selectedName: $("selectedNameInput"),
    selectedWidthField: $("selectedWidthField"),
    selectedHeightField: $("selectedHeightField"),
    selectedWidth: $("selectedWidthInput"),
    selectedHeight: $("selectedHeightInput"),
    selectedWidthLabel: $("selectedWidthLabel"),
    selectedHeightLabel: $("selectedHeightLabel"),
    selectedX: $("selectedXInput"),
    selectedY: $("selectedYInput"),
    selectedRotation: $("selectedRotationInput"),
    selectedTextSizeField: $("selectedTextSizeField"),
    selectedTextSize: $("selectedTextSizeInput"),
    doorSwingField: $("doorSwingField"),
    selectedDoorSwing: $("selectedDoorSwingInput"),
    selectedColor: $("selectedColorInput"),
    rotateLeft: $("rotateLeftButton"),
    resetRotation: $("resetRotationButton"),
    rotateRight: $("rotateRightButton"),
    itemCount: $("itemCountLabel"),
    legendGrid: $("legendGrid"),
    legendShape: $("legendShape"),
    legendArea: $("legendArea"),
    saveState: $("saveState"),
    newPlan: $("newPlanButton"),
    export: $("exportButton"),
    print: $("printButton"),
    toast: $("toast")
  };

  let state = {
    roomWidth: 800,
    roomHeight: 600,
    shapeMode: "rectangle",
    bottomWidth: 800,
    rightDepth: 600,
    alignment: "center",
    gridSize: 10,
    items: [],
    selectedId: null,
    zoom: 1
  };
  let history = [];
  let historyIndex = -1;
  let drag = null;
  let toastTimer = null;
  let saveTimer = null;

  function svgEl(name, attrs = {}) {
    const node = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function numeric(input, fallback, min, max) {
    const value = Number(input.value);
    return Number.isFinite(value) ? clamp(value, min, max) : fallback;
  }

  function snap(value) {
    return Math.round(value / state.gridSize) * state.gridSize;
  }

  function gridLegendText() {
    return `细格 ${state.gridSize} cm · 粗线 ${state.gridSize * 5}/${state.gridSize * 10} cm`;
  }

  function roomGeometry() {
    const topWidth = state.roomWidth;
    const bottomWidth = state.shapeMode === "rectangle" ? topWidth : state.bottomWidth;
    const leftDepth = state.roomHeight;
    const rightDepth = state.shapeMode === "rectangle" ? leftDepth : state.rightDepth;
    const width = Math.max(topWidth, bottomWidth);
    let topX = 0;
    let bottomX = 0;
    if (state.alignment === "right") {
      topX = width - topWidth;
      bottomX = width - bottomWidth;
    } else if (state.alignment === "center") {
      topX = (width - topWidth) / 2;
      bottomX = (width - bottomWidth) / 2;
    }
    const points = [
      { x: topX, y: 0 },
      { x: topX + topWidth, y: 0 },
      { x: bottomX + bottomWidth, y: rightDepth },
      { x: bottomX, y: leftDepth }
    ];
    const area = Math.abs(points.reduce((sum, point, index) => {
      const next = points[(index + 1) % points.length];
      return sum + point.x * next.y - next.x * point.y;
    }, 0)) / 2;
    return {
      points,
      width,
      height: Math.max(leftDepth, rightDepth),
      topWidth,
      bottomWidth,
      leftDepth,
      rightDepth,
      area
    };
  }

  function pointOnSegment(point, start, end) {
    const cross = (point.y - start.y) * (end.x - start.x) - (point.x - start.x) * (end.y - start.y);
    if (Math.abs(cross) > .01) return false;
    return point.x >= Math.min(start.x, end.x) - .01
      && point.x <= Math.max(start.x, end.x) + .01
      && point.y >= Math.min(start.y, end.y) - .01
      && point.y <= Math.max(start.y, end.y) + .01;
  }

  function pointInsideRoom(point) {
    const points = roomGeometry().points;
    let inside = false;
    for (let index = 0, previous = points.length - 1; index < points.length; previous = index++) {
      const start = points[previous];
      const end = points[index];
      if (pointOnSegment(point, start, end)) return true;
      const crosses = ((end.y > point.y) !== (start.y > point.y))
        && point.x < ((start.x - end.x) * (point.y - end.y)) / (start.y - end.y) + end.x;
      if (crosses) inside = !inside;
    }
    return inside;
  }

  function normalizeRotation(value) {
    const angle = Number(value) || 0;
    return ((angle % 360) + 360) % 360;
  }

  function isAnnotation(item) {
    return item.kind === "text" || item.kind === "arrow";
  }

  function itemCorners(item, x = item.x, y = item.y, width = item.width, height = item.height, rotation = item.rotation || 0) {
    const centerX = x + width / 2;
    const centerY = y + height / 2;
    const radians = normalizeRotation(rotation) * Math.PI / 180;
    const cosine = Math.cos(radians);
    const sine = Math.sin(radians);
    return [
      { x, y },
      { x: x + width, y },
      { x: x + width, y: y + height },
      { x, y: y + height }
    ].map((point) => {
      const dx = point.x - centerX;
      const dy = point.y - centerY;
      return {
        x: centerX + dx * cosine - dy * sine,
        y: centerY + dx * sine + dy * cosine
      };
    });
  }

  function itemFits(
    item,
    x = item.x,
    y = item.y,
    width = item.width,
    height = item.height,
    rotation = item.rotation || 0
  ) {
    return itemCorners(item, x, y, width, height, rotation).every(pointInsideRoom);
  }

  function findValidPosition(item, preferredX = item.x, preferredY = item.y) {
    if (itemFits(item, preferredX, preferredY)) return { x: preferredX, y: preferredY };
    const geometry = roomGeometry();
    const step = Math.max(state.gridSize, 10);
    let best = null;
    let bestDistance = Infinity;
    for (let y = 0; y <= geometry.height - item.height; y += step) {
      for (let x = 0; x <= geometry.width - item.width; x += step) {
        if (!itemFits(item, x, y)) continue;
        const distance = Math.abs(x - preferredX) + Math.abs(y - preferredY);
        if (distance < bestDistance) {
          best = { x, y };
          bestDistance = distance;
        }
      }
    }
    return best;
  }

  function clonePlan() {
    return JSON.parse(JSON.stringify({
      roomWidth: state.roomWidth,
      roomHeight: state.roomHeight,
      shapeMode: state.shapeMode,
      bottomWidth: state.bottomWidth,
      rightDepth: state.rightDepth,
      alignment: state.alignment,
      gridSize: state.gridSize,
      items: state.items
    }));
  }

  function recordHistory() {
    const snapshot = clonePlan();
    const serialized = JSON.stringify(snapshot);
    if (historyIndex >= 0 && JSON.stringify(history[historyIndex]) === serialized) return;
    history = history.slice(0, historyIndex + 1);
    history.push(snapshot);
    if (history.length > 80) history.shift();
    historyIndex = history.length - 1;
    updateHistoryButtons();
    scheduleSave();
  }

  function restoreSnapshot(snapshot) {
    state = { ...state, ...JSON.parse(JSON.stringify(snapshot)), selectedId: null };
    syncInputs();
    render();
    scheduleSave();
  }

  function undo() {
    if (historyIndex <= 0) return;
    historyIndex -= 1;
    restoreSnapshot(history[historyIndex]);
    updateHistoryButtons();
  }

  function redo() {
    if (historyIndex >= history.length - 1) return;
    historyIndex += 1;
    restoreSnapshot(history[historyIndex]);
    updateHistoryButtons();
  }

  function updateHistoryButtons() {
    els.undo.disabled = historyIndex <= 0;
    els.redo.disabled = historyIndex >= history.length - 1;
  }

  function scheduleSave() {
    els.saveState.textContent = "正在保存…";
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(clonePlan()));
      els.saveState.textContent = "已自动保存";
    }, 180);
  }

  function loadSaved() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_STORAGE_KEY) || "null");
      if (!saved || !saved.roomWidth || !saved.roomHeight || !Array.isArray(saved.items)) return false;
      state = {
        ...state,
        roomWidth: clamp(Number(saved.roomWidth), 100, 10000),
        roomHeight: clamp(Number(saved.roomHeight), 100, 10000),
        shapeMode: saved.shapeMode === "quadrilateral" ? "quadrilateral" : "rectangle",
        bottomWidth: clamp(Number(saved.bottomWidth || saved.roomWidth), 100, 10000),
        rightDepth: clamp(Number(saved.rightDepth || saved.roomHeight), 100, 10000),
        alignment: ["left", "center", "right"].includes(saved.alignment) ? saved.alignment : "center",
        gridSize: clamp(Number(saved.gridSize) || 10, 1, 500),
        items: saved.items.map((item) => {
          const kind = ["door", "text", "arrow"].includes(item.kind) ? item.kind : "equipment";
          return {
            ...item,
            id: String(item.id),
            rotation: normalizeRotation(item.rotation),
            kind,
            fontSize: kind === "text" ? clamp(Number(item.fontSize) || 22, 8, 80) : undefined,
            swing: item.swing === "left" ? "left" : "right"
          };
        })
      };
      return true;
    } catch (error) {
      console.warn("无法读取已保存平面图", error);
      return false;
    }
  }

  function syncInputs() {
    els.roomWidth.value = state.roomWidth;
    els.roomHeight.value = state.roomHeight;
    els.roomType.value = state.shapeMode;
    els.bottomWidth.value = state.bottomWidth;
    els.rightDepth.value = state.rightDepth;
    els.roomAlignment.value = state.alignment;
    els.gridSize.value = state.gridSize;
    els.legendGrid.textContent = gridLegendText();
    updateRoomTypeFields();
  }

  function updateRoomTypeFields() {
    const irregular = els.roomType.value === "quadrilateral";
    els.shapeFields.hidden = !irregular;
    els.topWidthLabel.textContent = irregular ? "上边宽度" : "横向宽度";
    els.leftDepthLabel.textContent = irregular ? "左侧进深" : "纵向长度";
    if (!irregular) {
      els.bottomWidth.value = els.roomWidth.value;
      els.rightDepth.value = els.roomHeight.value;
    }
  }

  function renderModels() {
    els.modelList.innerHTML = "";
    MODELS.forEach((model) => {
      if (model.kind === "door") {
        const card = document.createElement("div");
        card.className = "model-button door-model-card";
        card.innerHTML = `
          <span class="model-swatch" style="background:${model.color}">${model.abbr}</span>
          <span><strong>${model.name}</strong><small>门洞宽度</small></span>
          <div class="door-width-control">
            <input type="number" min="40" max="300" step="1" value="${model.width}" aria-label="门洞宽度 cm" />
            <em>cm</em>
          </div>
          <button type="button" aria-label="添加门">＋</button>
        `;
        const widthInput = card.querySelector("input");
        card.querySelector("button").addEventListener("click", () => {
          addItem(model, numeric(widthInput, model.width, 40, 300));
        });
        els.modelList.appendChild(card);
        return;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "model-button";
      button.innerHTML = `
        <span class="model-swatch" style="background:${model.color}">${model.abbr}</span>
        <span><strong>${model.name}</strong><small>${model.kind === "door" ? `常用门洞 ${model.width} cm` : `常用 ${model.width} × ${model.height} cm`}</small></span>
        <b aria-hidden="true">＋</b>
      `;
      button.addEventListener("click", () => addItem(model));
      els.modelList.appendChild(button);
    });
  }

  function updateRoom() {
    const before = JSON.stringify(clonePlan());
    state.shapeMode = els.roomType.value === "quadrilateral" ? "quadrilateral" : "rectangle";
    state.roomWidth = numeric(els.roomWidth, state.roomWidth, 100, 10000);
    state.roomHeight = numeric(els.roomHeight, state.roomHeight, 100, 10000);
    state.bottomWidth = state.shapeMode === "rectangle"
      ? state.roomWidth
      : numeric(els.bottomWidth, state.bottomWidth, 100, 10000);
    state.rightDepth = state.shapeMode === "rectangle"
      ? state.roomHeight
      : numeric(els.rightDepth, state.rightDepth, 100, 10000);
    state.alignment = ["left", "center", "right"].includes(els.roomAlignment.value)
      ? els.roomAlignment.value
      : "center";
    let outsideCount = 0;
    state.items.forEach((item) => {
      const position = findValidPosition(item, item.x, item.y);
      if (position) {
        item.x = position.x;
        item.y = position.y;
      } else {
        outsideCount += 1;
      }
    });
    syncInputs();
    recordHistory();
    render();
    fitToCanvas();
    if (outsideCount) {
      showToast(`${outsideCount} 个设备尺寸过大，暂时超出新轮廓`);
    } else {
      showToast(before === JSON.stringify(clonePlan()) ? "轮廓尺寸未变化" : "门店轮廓已更新");
    }
  }

  function addItem(model, widthOverride = null) {
    const width = widthOverride ?? numeric(els.itemWidth, model.width, 10, 3000);
    const height = model.kind === "door"
      ? width
      : numeric(els.itemHeight, model.height, 10, 3000);
    const geometry = roomGeometry();
    if (width > geometry.width || height > geometry.height) {
      showToast("设备尺寸大于门店轮廓，请先调整尺寸");
      return;
    }
    const offset = (state.items.length % 7) * state.gridSize * 2;
    const item = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      name: model.name,
      width,
      height,
      x: snap(state.gridSize * 4 + offset),
      y: snap(state.gridSize * 4 + offset),
      rotation: 0,
      color: model.color,
      kind: model.kind || "equipment",
      swing: "right"
    };
    const position = findValidPosition(item, item.x, item.y);
    if (!position) {
      showToast("当前轮廓内没有足够空间放置该设备");
      return;
    }
    item.x = position.x;
    item.y = position.y;
    state.items.push(item);
    state.selectedId = item.id;
    recordHistory();
    render();
    showToast(model.kind === "door"
      ? `已添加 ${item.width} cm 门洞`
      : `已添加${model.name} ${item.width}×${item.height} cm`);
  }

  function addAnnotation(kind) {
    const isText = kind === "text";
    const geometry = roomGeometry();
    const width = Math.min(isText ? 180 : 140, Math.max(30, geometry.width));
    const height = Math.min(isText ? 44 : 30, Math.max(20, geometry.height));
    if (width > geometry.width || height > geometry.height) {
      showToast("当前门店轮廓太小，无法添加标注");
      return;
    }
    const offset = (state.items.length % 7) * state.gridSize * 2;
    const item = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      name: isText ? "请输入标注" : "箭头",
      width,
      height,
      x: snap(state.gridSize * 4 + offset),
      y: snap(state.gridSize * 4 + offset),
      rotation: 0,
      color: isText ? "#1f2937" : "#d94a26",
      kind,
      fontSize: isText ? 22 : undefined
    };
    const position = findValidPosition(item, item.x, item.y);
    if (!position) {
      showToast("当前轮廓内没有足够空间放置标注");
      return;
    }
    item.x = position.x;
    item.y = position.y;
    state.items.push(item);
    state.selectedId = item.id;
    recordHistory();
    render();
    showToast(isText ? "已添加文本标注，请在右侧修改内容" : "已添加箭头标注");
  }

  function drawDimension(start, end, label) {
    const geometry = roomGeometry();
    const centroid = geometry.points.reduce(
      (sum, point) => ({ x: sum.x + point.x / 4, y: sum.y + point.y / 4 }),
      { x: 0, y: 0 }
    );
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const length = Math.hypot(dx, dy) || 1;
    let nx = -dy / length;
    let ny = dx / length;
    const midpoint = { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 };
    if ((midpoint.x - centroid.x) * nx + (midpoint.y - centroid.y) * ny < 0) {
      nx *= -1;
      ny *= -1;
    }
    const offset = 30;
    const q1 = { x: start.x + nx * offset, y: start.y + ny * offset };
    const q2 = { x: end.x + nx * offset, y: end.y + ny * offset };
    const group = svgEl("g", { class: "room-dimension" });
    group.appendChild(svgEl("line", { x1: q1.x, y1: q1.y, x2: q2.x, y2: q2.y, class: "dimension-line" }));
    const tick = 7;
    group.appendChild(svgEl("line", {
      x1: q1.x - nx * tick, y1: q1.y - ny * tick,
      x2: q1.x + nx * tick, y2: q1.y + ny * tick, class: "dimension-tick"
    }));
    group.appendChild(svgEl("line", {
      x1: q2.x - nx * tick, y1: q2.y - ny * tick,
      x2: q2.x + nx * tick, y2: q2.y + ny * tick, class: "dimension-tick"
    }));
    const textX = midpoint.x + nx * (offset + 14);
    const textY = midpoint.y + ny * (offset + 14);
    let angle = Math.atan2(dy, dx) * 180 / Math.PI;
    if (angle > 90 || angle < -90) angle += 180;
    const text = svgEl("text", {
      x: textX, y: textY, class: "dimension-text",
      transform: `rotate(${angle} ${textX} ${textY})`
    });
    text.textContent = label;
    group.appendChild(text);
    els.roomLayer.appendChild(group);
  }

  function renderRoom() {
    els.roomLayer.innerHTML = "";
    const geometry = roomGeometry();
    const points = geometry.points.map((point) => `${point.x},${point.y}`).join(" ");
    els.roomClipPolygon.setAttribute("points", points);
    const room = svgEl("polygon", { points, class: "room-outline" });
    els.roomLayer.appendChild(room);
    drawDimension(geometry.points[0], geometry.points[1], `${geometry.topWidth} cm`);
    drawDimension(geometry.points[1], geometry.points[2], `${geometry.rightDepth} cm`);
    drawDimension(geometry.points[2], geometry.points[3], `${geometry.bottomWidth} cm`);
    drawDimension(geometry.points[3], geometry.points[0], `${geometry.leftDepth} cm`);
  }

  function renderGrid() {
    const minor = state.gridSize;
    const major = minor * 5;
    const meter = minor * 10;
    els.minorGrid.setAttribute("width", minor);
    els.minorGrid.setAttribute("height", minor);
    els.minorGridPath.setAttribute("d", `M ${minor} 0 L 0 0 0 ${minor}`);
    els.majorGrid.setAttribute("width", major);
    els.majorGrid.setAttribute("height", major);
    els.majorGridMinorFill.setAttribute("width", major);
    els.majorGridMinorFill.setAttribute("height", major);
    els.majorGridPath.setAttribute("d", `M ${major} 0 L 0 0 0 ${major}`);
    els.meterGrid.setAttribute("width", meter);
    els.meterGrid.setAttribute("height", meter);
    els.meterGridMajorFill.setAttribute("width", meter);
    els.meterGridMajorFill.setAttribute("height", meter);
    els.meterGridPath.setAttribute("d", `M ${meter} 0 L 0 0 0 ${meter}`);
    els.gridBackground.setAttribute("x", 0);
    els.gridBackground.setAttribute("y", 0);
    const geometry = roomGeometry();
    els.gridBackground.setAttribute("width", geometry.width);
    els.gridBackground.setAttribute("height", geometry.height);
  }

  function renderItems() {
    els.itemLayer.innerHTML = "";
    state.items.forEach((item) => {
      const selected = item.id === state.selectedId;
      const group = svgEl("g", {
        class: `equipment-item${selected ? " selected" : ""}`,
        "data-id": item.id,
        transform: `translate(${item.x} ${item.y}) rotate(${item.rotation || 0} ${item.width / 2} ${item.height / 2})`
      });
      if (item.kind === "door") {
        const hingeOnLeft = item.swing !== "left";
        const hingeX = hingeOnLeft ? 0 : item.width;
        const farX = hingeOnLeft ? item.width : 0;
        const hitbox = svgEl("rect", {
          x: 0, y: 0, width: item.width, height: item.height,
          class: "door-hitbox"
        });
        const opening = svgEl("line", {
          x1: hingeX, y1: item.height, x2: farX, y2: item.height,
          class: "door-opening"
        });
        const leaf = svgEl("line", {
          x1: hingeX, y1: item.height, x2: hingeX, y2: 0,
          class: "door-leaf"
        });
        const arc = svgEl("path", {
          d: hingeOnLeft
            ? `M 0 0 A ${item.width} ${item.height} 0 0 1 ${item.width} ${item.height}`
            : `M ${item.width} 0 A ${item.width} ${item.height} 0 0 0 0 ${item.height}`,
          class: "door-swing-arc"
        });
        const hinge = svgEl("circle", {
          cx: hingeX, cy: item.height, r: 4, class: "door-hinge"
        });
        const label = svgEl("text", {
          x: item.width / 2, y: item.height - 8, class: "door-label"
        });
        label.textContent = `门 ${item.width} cm`;
        group.append(hitbox, opening, leaf, arc, hinge, label);
      } else if (item.kind === "text") {
        const hitbox = svgEl("rect", {
          x: 0, y: 0, width: item.width, height: item.height,
          rx: 5, class: "annotation-hitbox"
        });
        const text = svgEl("text", {
          x: item.width / 2,
          y: item.height / 2,
          fill: item.color,
          class: "annotation-text",
          "font-size": clamp(Number(item.fontSize) || 22, 8, 80)
        });
        text.textContent = item.name;
        group.append(hitbox, text);
      } else if (item.kind === "arrow") {
        const midpointY = item.height / 2;
        const tipX = Math.max(8, item.width - 4);
        const headLength = clamp(item.width * .18, 8, 22);
        const headHalfHeight = clamp(item.height * .32, 6, 12);
        const headBaseX = Math.max(4, tipX - headLength);
        const hitbox = svgEl("rect", {
          x: 0, y: 0, width: item.width, height: item.height,
          rx: 5, class: "annotation-hitbox"
        });
        const line = svgEl("line", {
          x1: 5, y1: midpointY, x2: headBaseX + 1, y2: midpointY,
          stroke: item.color, class: "annotation-arrow-line"
        });
        const head = svgEl("polygon", {
          points: `${tipX},${midpointY} ${headBaseX},${midpointY - headHalfHeight} ${headBaseX},${midpointY + headHalfHeight}`,
          fill: item.color, class: "annotation-arrow-head"
        });
        group.append(hitbox, line, head);
      } else {
        const box = svgEl("rect", {
          x: 0, y: 0, width: item.width, height: item.height,
          rx: Math.min(8, item.width / 8, item.height / 8),
          fill: item.color, class: "item-box"
        });
        const name = svgEl("text", {
          x: item.width / 2, y: item.height / 2 - 4,
          class: "item-name"
        });
        name.textContent = item.name;
        const size = svgEl("text", {
          x: item.width / 2, y: item.height / 2 + 12,
          class: "item-size"
        });
        size.textContent = `${item.width} × ${item.height} cm`;
        group.append(box, name, size);
      }
      if (selected) {
        group.appendChild(svgEl("rect", {
          x: -5, y: -5, width: item.width + 10, height: item.height + 10,
          rx: 8, class: "selection-ring"
        }));
      }
      group.addEventListener("pointerdown", beginDrag);
      els.itemLayer.appendChild(group);
    });
  }

  function itemBounds(item) {
    const corners = itemCorners(item);
    const xs = corners.map((point) => point.x);
    const ys = corners.map((point) => point.y);
    return {
      left: Math.min(...xs),
      right: Math.max(...xs),
      top: Math.min(...ys),
      bottom: Math.max(...ys)
    };
  }

  function rangesOverlap(startA, endA, startB, endB) {
    return Math.min(endA, endB) - Math.max(startA, startB) > .01;
  }

  function formatDistance(value) {
    return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "");
  }

  function drawSpacingGuide(x1, y1, x2, y2, distance, vertical = false) {
    const group = svgEl("g", { class: "spacing-guide-group" });
    group.appendChild(svgEl("line", {
      x1, y1, x2, y2, class: "spacing-guide-line"
    }));
    const tick = 6;
    if (vertical) {
      group.appendChild(svgEl("line", {
        x1: x1 - tick, y1, x2: x1 + tick, y2: y1, class: "spacing-guide-tick"
      }));
      group.appendChild(svgEl("line", {
        x1: x2 - tick, y1: y2, x2: x2 + tick, y2, class: "spacing-guide-tick"
      }));
    } else {
      group.appendChild(svgEl("line", {
        x1, y1: y1 - tick, x2: x1, y2: y1 + tick, class: "spacing-guide-tick"
      }));
      group.appendChild(svgEl("line", {
        x1: x2, y1: y2 - tick, x2, y2: y2 + tick, class: "spacing-guide-tick"
      }));
    }
    const textX = (x1 + x2) / 2;
    const textY = (y1 + y2) / 2;
    const text = svgEl("text", {
      x: vertical ? textX + 12 : textX,
      y: vertical ? textY + 4 : textY - 8,
      class: "spacing-guide-text"
    });
    text.textContent = `${formatDistance(distance)} cm`;
    group.appendChild(text);
    els.guideLayer.appendChild(group);
  }

  function renderGuides() {
    els.guideLayer.innerHTML = "";
    const selected = selectedItem();
    if (!selected || isAnnotation(selected) || state.items.length < 2) return;
    const selectedBounds = itemBounds(selected);
    const candidates = {
      left: [],
      right: [],
      up: [],
      down: []
    };
    state.items.forEach((item) => {
      if (item.id === selected.id || isAnnotation(item)) return;
      const bounds = itemBounds(item);
      if (rangesOverlap(selectedBounds.top, selectedBounds.bottom, bounds.top, bounds.bottom)) {
        if (bounds.right <= selectedBounds.left) {
          candidates.left.push({ bounds, gap: selectedBounds.left - bounds.right });
        }
        if (bounds.left >= selectedBounds.right) {
          candidates.right.push({ bounds, gap: bounds.left - selectedBounds.right });
        }
      }
      if (rangesOverlap(selectedBounds.left, selectedBounds.right, bounds.left, bounds.right)) {
        if (bounds.bottom <= selectedBounds.top) {
          candidates.up.push({ bounds, gap: selectedBounds.top - bounds.bottom });
        }
        if (bounds.top >= selectedBounds.bottom) {
          candidates.down.push({ bounds, gap: bounds.top - selectedBounds.bottom });
        }
      }
    });
    Object.values(candidates).forEach((items) => items.sort((a, b) => a.gap - b.gap));
    if (candidates.left[0]) {
      const target = candidates.left[0];
      const y = (Math.max(selectedBounds.top, target.bounds.top) + Math.min(selectedBounds.bottom, target.bounds.bottom)) / 2;
      drawSpacingGuide(target.bounds.right, y, selectedBounds.left, y, target.gap);
    }
    if (candidates.right[0]) {
      const target = candidates.right[0];
      const y = (Math.max(selectedBounds.top, target.bounds.top) + Math.min(selectedBounds.bottom, target.bounds.bottom)) / 2;
      drawSpacingGuide(selectedBounds.right, y, target.bounds.left, y, target.gap);
    }
    if (candidates.up[0]) {
      const target = candidates.up[0];
      const x = (Math.max(selectedBounds.left, target.bounds.left) + Math.min(selectedBounds.right, target.bounds.right)) / 2;
      drawSpacingGuide(x, target.bounds.bottom, x, selectedBounds.top, target.gap, true);
    }
    if (candidates.down[0]) {
      const target = candidates.down[0];
      const x = (Math.max(selectedBounds.left, target.bounds.left) + Math.min(selectedBounds.right, target.bounds.right)) / 2;
      drawSpacingGuide(x, selectedBounds.bottom, x, target.bounds.top, target.gap, true);
    }
  }

  function render() {
    const geometry = roomGeometry();
    renderGrid();
    renderRoom();
    renderItems();
    renderGuides();
    renderProperties();
    els.emptyHint.hidden = true;
    const annotationCount = state.items.filter(isAnnotation).length;
    const equipmentCount = state.items.length - annotationCount;
    els.itemCount.textContent = `${equipmentCount} 个设备 · ${annotationCount} 个标注`;
    els.legendGrid.textContent = gridLegendText();
    els.legendShape.textContent = state.shapeMode === "quadrilateral" ? "上下边不同 / 斜墙" : "标准矩形";
    els.legendArea.textContent = `${(geometry.area / 10000).toFixed(2)} ㎡`;
    els.zoomLabel.textContent = `${Math.round(state.zoom * 100)}%`;
  }

  function selectedItem() {
    return state.items.find((item) => item.id === state.selectedId) || null;
  }

  function renderProperties() {
    const item = selectedItem();
    const hasSelection = Boolean(item);
    els.noSelection.hidden = hasSelection;
    els.propertyForm.hidden = !hasSelection;
    els.selectionHint.textContent = hasSelection ? `当前：${item.name}` : "请选择画布中的对象";
    els.duplicate.disabled = !hasSelection;
    els.rotate.disabled = !hasSelection;
    els.delete.disabled = !hasSelection;
    if (!item) return;
    const isDoor = item.kind === "door";
    const isText = item.kind === "text";
    const isArrow = item.kind === "arrow";
    els.selectedNameField.hidden = isArrow;
    els.selectedNameLabel.textContent = isText ? "标注文字" : "设备名称";
    els.selectedName.value = item.name;
    els.selectedWidth.value = item.width;
    els.selectedHeight.value = item.height;
    els.selectedWidth.min = isArrow ? 30 : 10;
    els.selectedWidthLabel.textContent = isDoor
      ? "门洞宽度 W"
      : isText
        ? "文字区域宽度 W"
        : isArrow
          ? "箭头长度 L"
          : "宽度 W";
    els.selectedHeightLabel.textContent = isDoor ? "开启范围 D" : "深度 D";
    els.selectedHeight.disabled = isDoor;
    els.selectedHeightField.hidden = isText || isArrow;
    els.selectedTextSizeField.hidden = !isText;
    els.selectedTextSize.value = isText ? clamp(Number(item.fontSize) || 22, 8, 80) : 22;
    els.doorSwingField.hidden = !isDoor;
    els.selectedDoorSwing.value = item.swing === "left" ? "left" : "right";
    els.selectedX.value = item.x;
    els.selectedY.value = item.y;
    els.selectedRotation.value = normalizeRotation(item.rotation);
    const geometry = roomGeometry();
    els.selectedX.max = Math.max(0, geometry.width - item.width);
    els.selectedY.max = Math.max(0, geometry.height - item.height);
    els.selectedColor.value = item.color;
  }

  function clientToRoom(event) {
    const point = els.svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const matrix = els.scene.getScreenCTM();
    return matrix ? point.matrixTransform(matrix.inverse()) : { x: 0, y: 0 };
  }

  function beginDrag(event) {
    if (event.button !== 0) return;
    event.stopPropagation();
    const group = event.currentTarget;
    const item = state.items.find((candidate) => candidate.id === group.dataset.id);
    if (!item) return;
    state.selectedId = item.id;
    const point = clientToRoom(event);
    drag = {
      id: item.id,
      offsetX: point.x - item.x,
      offsetY: point.y - item.y,
      startX: item.x,
      startY: item.y,
      pointerId: event.pointerId
    };
    renderProperties();
    renderItems();
    const activeGroup = els.itemLayer.querySelector(`[data-id="${CSS.escape(item.id)}"]`);
    if (activeGroup) {
      activeGroup.classList.add("dragging");
      activeGroup.setPointerCapture(event.pointerId);
    }
  }

  function moveDrag(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const item = selectedItem();
    if (!item) return;
    const point = clientToRoom(event);
    const geometry = roomGeometry();
    const nextX = snap(clamp(point.x - drag.offsetX, 0, Math.max(0, geometry.width - item.width)));
    const nextY = snap(clamp(point.y - drag.offsetY, 0, Math.max(0, geometry.height - item.height)));
    if (itemFits(item, nextX, nextY)) {
      item.x = nextX;
      item.y = nextY;
    }
    const group = els.itemLayer.querySelector(`[data-id="${CSS.escape(item.id)}"]`);
    if (group) {
      group.setAttribute(
        "transform",
        `translate(${item.x} ${item.y}) rotate(${item.rotation || 0} ${item.width / 2} ${item.height / 2})`
      );
    }
    renderProperties();
    renderGuides();
  }

  function endDrag(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const item = selectedItem();
    const moved = item && (item.x !== drag.startX || item.y !== drag.startY);
    drag = null;
    if (moved) recordHistory();
    renderItems();
    renderGuides();
  }

  function applyProperties(event) {
    event.preventDefault();
    const item = selectedItem();
    if (!item) return;
    const geometry = roomGeometry();
    const isText = item.kind === "text";
    const isArrow = item.kind === "arrow";
    const minimumWidth = isArrow ? 30 : 10;
    const nextWidth = numeric(els.selectedWidth, item.width, minimumWidth, Math.min(3000, geometry.width));
    const nextFontSize = isText
      ? numeric(els.selectedTextSize, item.fontSize || 22, 8, 80)
      : item.fontSize;
    const nextHeight = item.kind === "door"
      ? nextWidth
      : isText
        ? clamp(nextFontSize * 2, 24, Math.min(3000, geometry.height))
        : isArrow
          ? item.height
          : numeric(els.selectedHeight, item.height, 10, Math.min(3000, geometry.height));
    const nextX = clamp(numeric(els.selectedX, item.x, 0, geometry.width), 0, geometry.width - nextWidth);
    const nextY = clamp(numeric(els.selectedY, item.y, 0, geometry.height), 0, geometry.height - nextHeight);
    const nextRotation = normalizeRotation(numeric(els.selectedRotation, item.rotation || 0, -359, 359));
    if (!itemFits(item, nextX, nextY, nextWidth, nextHeight, nextRotation)) {
      showToast("该位置或尺寸会超出门店轮廓");
      renderProperties();
      return;
    }
    item.name = els.selectedName.value.trim() || item.name;
    item.width = nextWidth;
    item.height = nextHeight;
    item.x = nextX;
    item.y = nextY;
    item.rotation = nextRotation;
    item.color = els.selectedColor.value;
    item.fontSize = isText ? nextFontSize : item.fontSize;
    item.swing = item.kind === "door" && els.selectedDoorSwing.value === "left" ? "left" : "right";
    recordHistory();
    render();
    showToast(isAnnotation(item) ? "标注属性已更新" : "设备属性已更新");
  }

  function duplicateSelected() {
    const item = selectedItem();
    if (!item) return;
    const copy = {
      ...item,
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      x: snap(item.x + state.gridSize * 2),
      y: snap(item.y + state.gridSize * 2)
    };
    const position = findValidPosition(copy, copy.x, copy.y);
    if (!position) {
      showToast("轮廓内没有足够空间复制该设备");
      return;
    }
    copy.x = position.x;
    copy.y = position.y;
    state.items.push(copy);
    state.selectedId = copy.id;
    recordHistory();
    render();
    showToast(`已复制${copy.name}`);
  }

  function rotateSelected() {
    const item = selectedItem();
    if (!item) return;
    const nextRotation = normalizeRotation((item.rotation || 0) + 90);
    const rotated = { ...item, rotation: nextRotation };
    const position = findValidPosition(rotated, item.x, item.y);
    if (!position) {
      showToast("旋转后轮廓内没有足够空间");
      return;
    }
    item.rotation = nextRotation;
    item.x = position.x;
    item.y = position.y;
    recordHistory();
    render();
  }

  function adjustRotation(delta, absolute = false) {
    const item = selectedItem();
    if (!item) return;
    const nextRotation = normalizeRotation(absolute ? delta : (item.rotation || 0) + delta);
    if (!itemFits(item, item.x, item.y, item.width, item.height, nextRotation)) {
      showToast("该角度会使设备超出门店轮廓");
      return;
    }
    item.rotation = nextRotation;
    recordHistory();
    render();
  }

  function nudgeSelected(deltaX, deltaY) {
    const item = selectedItem();
    if (!item) return;
    const nextX = item.x + deltaX;
    const nextY = item.y + deltaY;
    if (!itemFits(item, nextX, nextY)) {
      showToast("已到门店轮廓边界");
      return;
    }
    item.x = nextX;
    item.y = nextY;
    recordHistory();
    render();
  }

  function deleteSelected() {
    const item = selectedItem();
    if (!item) return;
    state.items = state.items.filter((candidate) => candidate.id !== item.id);
    state.selectedId = null;
    recordHistory();
    render();
    showToast(`已删除${item.name}`);
  }

  function setZoom(nextZoom) {
    state.zoom = clamp(nextZoom, 0.25, 3);
    updateViewBox();
  }

  function sceneBounds() {
    const padding = 74;
    const geometry = roomGeometry();
    const baseWidth = geometry.width + padding * 2;
    const baseHeight = geometry.height + padding * 2;
    return { x: -padding, y: -padding, width: baseWidth, height: baseHeight };
  }

  function updateViewBox() {
    const bounds = sceneBounds();
    const width = bounds.width / state.zoom;
    const height = bounds.height / state.zoom;
    const centerX = bounds.x + bounds.width / 2;
    const centerY = bounds.y + bounds.height / 2;
    els.svg.setAttribute("viewBox", `${centerX - width / 2} ${centerY - height / 2} ${width} ${height}`);
    els.zoomLabel.textContent = `${Math.round(state.zoom * 100)}%`;
  }

  function fitToCanvas() {
    state.zoom = 1;
    updateViewBox();
  }

  function updateGridSize() {
    const next = numeric(els.gridSize, state.gridSize, 1, 500);
    state.gridSize = next;
    state.items.forEach((item) => {
      const position = findValidPosition(item, snap(item.x), snap(item.y));
      if (position) {
        item.x = position.x;
        item.y = position.y;
      }
    });
    syncInputs();
    recordHistory();
    render();
    showToast(`网格已设为 ${next} cm / 格`);
  }

  function resetPlan() {
    const confirmed = window.confirm("新建平面图会清空当前设备，确定继续吗？");
    if (!confirmed) return;
    state = {
      ...state,
      roomWidth: 800,
      roomHeight: 600,
      shapeMode: "rectangle",
      bottomWidth: 800,
      rightDepth: 600,
      alignment: "center",
      gridSize: 10,
      items: [],
      selectedId: null,
      zoom: 1
    };
    history = [];
    historyIndex = -1;
    syncInputs();
    recordHistory();
    render();
    fitToCanvas();
    showToast("已新建空白平面图");
  }

  function exportImage() {
    const bounds = sceneBounds();
    const clone = els.svg.cloneNode(true);
    clone.setAttribute("width", Math.round(bounds.width * 1.6));
    clone.setAttribute("height", Math.round(bounds.height * 1.6));
    clone.setAttribute("viewBox", `${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`);
    clone.querySelectorAll(".selection-ring").forEach((node) => node.remove());
    clone.querySelectorAll(".spacing-guide-group").forEach((node) => node.remove());
    const style = svgEl("style");
    style.textContent = `
      .room-outline{fill:rgba(255,255,255,.18);stroke:#182230;stroke-width:3}
      .dimension-line,.dimension-tick{stroke:#687384;stroke-width:1.2}
      .dimension-text{fill:#344054;font:800 14px sans-serif;text-anchor:middle;paint-order:stroke;stroke:#f8fafc;stroke-width:5px;stroke-linejoin:round}
      .item-box{stroke:rgba(17,24,39,.54);stroke-width:1.4}
      .item-name{fill:#fff;font:850 13px sans-serif;text-anchor:middle}
      .item-size{fill:rgba(255,255,255,.9);font:650 9px sans-serif;text-anchor:middle}
      .door-hitbox{fill:rgba(180,120,60,.035)}
      .door-opening,.door-leaf{fill:none;stroke:#7a4c22;stroke-width:3}
      .door-opening{stroke-dasharray:5 4;opacity:.75}
      .door-swing-arc{fill:none;stroke:#a87337;stroke-width:1.6;stroke-dasharray:5 4}
      .door-hinge{fill:#7a4c22}
      .door-label{fill:#7a4c22;font:850 10px sans-serif;text-anchor:middle;paint-order:stroke;stroke:#fff;stroke-width:4px}
      .annotation-hitbox{fill:rgba(255,255,255,.01)}
      .annotation-text{font-weight:850;text-anchor:middle;dominant-baseline:middle;paint-order:stroke;stroke:rgba(255,255,255,.96);stroke-width:5px;stroke-linejoin:round}
      .annotation-arrow-line{fill:none;stroke-width:4;stroke-linecap:round}
    `;
    clone.insertBefore(style, clone.firstChild);
    const source = new XMLSerializer().serializeToString(clone);
    const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext("2d");
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0);
      URL.revokeObjectURL(url);
      const link = document.createElement("a");
      const geometry = roomGeometry();
      link.download = state.shapeMode === "quadrilateral"
        ? `门店平面图-上${geometry.topWidth}-下${geometry.bottomWidth}cm.png`
        : `门店平面图-${state.roomWidth}x${state.roomHeight}cm.png`;
      link.href = canvas.toDataURL("image/png");
      link.click();
      showToast("平面图图片已导出");
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      showToast("图片导出失败，请使用打印 / PDF");
    };
    image.src = url;
  }

  function showToast(message) {
    els.toast.textContent = message;
    els.toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toast.classList.remove("show"), 2200);
  }

  function handleKeyboard(event) {
    const tag = event.target.tagName;
    const editing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    const modifier = event.metaKey || event.ctrlKey;
    if (modifier && event.key.toLowerCase() === "z") {
      event.preventDefault();
      event.shiftKey ? redo() : undo();
      return;
    }
    if (modifier && event.key.toLowerCase() === "d" && !editing) {
      event.preventDefault();
      duplicateSelected();
      return;
    }
    if (editing) return;
    const nudgeStep = event.shiftKey ? state.gridSize : 1;
    const arrowMoves = {
      ArrowUp: [0, -nudgeStep],
      ArrowDown: [0, nudgeStep],
      ArrowLeft: [-nudgeStep, 0],
      ArrowRight: [nudgeStep, 0]
    };
    if (arrowMoves[event.key]) {
      event.preventDefault();
      nudgeSelected(...arrowMoves[event.key]);
      return;
    }
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      deleteSelected();
    } else if (event.key.toLowerCase() === "r") {
      event.preventDefault();
      rotateSelected();
    } else if (event.key === "[") {
      event.preventDefault();
      adjustRotation(event.shiftKey ? -5 : -1);
    } else if (event.key === "]") {
      event.preventDefault();
      adjustRotation(event.shiftKey ? 5 : 1);
    } else if (event.key === "Escape") {
      state.selectedId = null;
      render();
    }
  }

  function bindEvents() {
    els.updateRoom.addEventListener("click", updateRoom);
    els.roomType.addEventListener("change", updateRoomTypeFields);
    els.roomWidth.addEventListener("input", () => {
      if (els.roomType.value === "rectangle") els.bottomWidth.value = els.roomWidth.value;
    });
    els.roomHeight.addEventListener("input", () => {
      if (els.roomType.value === "rectangle") els.rightDepth.value = els.roomHeight.value;
    });
    els.gridSize.addEventListener("change", updateGridSize);
    els.propertyForm.addEventListener("submit", applyProperties);
    els.selectedWidth.addEventListener("input", () => {
      if (selectedItem()?.kind === "door") els.selectedHeight.value = els.selectedWidth.value;
    });
    els.undo.addEventListener("click", undo);
    els.redo.addEventListener("click", redo);
    els.addText.addEventListener("click", () => addAnnotation("text"));
    els.addArrow.addEventListener("click", () => addAnnotation("arrow"));
    els.duplicate.addEventListener("click", duplicateSelected);
    els.rotate.addEventListener("click", rotateSelected);
    els.rotateLeft.addEventListener("click", () => adjustRotation(-5));
    els.resetRotation.addEventListener("click", () => adjustRotation(0, true));
    els.rotateRight.addEventListener("click", () => adjustRotation(5));
    els.delete.addEventListener("click", deleteSelected);
    els.zoomOut.addEventListener("click", () => setZoom(state.zoom - .15));
    els.zoomIn.addEventListener("click", () => setZoom(state.zoom + .15));
    els.fit.addEventListener("click", fitToCanvas);
    els.newPlan.addEventListener("click", resetPlan);
    els.export.addEventListener("click", exportImage);
    els.print.addEventListener("click", () => window.print());
    els.svg.addEventListener("pointermove", moveDrag);
    els.svg.addEventListener("pointerup", endDrag);
    els.svg.addEventListener("pointercancel", endDrag);
    els.svg.addEventListener("pointerdown", (event) => {
      if (event.target.closest(".equipment-item")) return;
      state.selectedId = null;
      render();
    });
    window.addEventListener("keydown", handleKeyboard);
    window.addEventListener("resize", updateViewBox);
  }

  function init() {
    renderModels();
    loadSaved();
    syncInputs();
    bindEvents();
    recordHistory();
    render();
    fitToCanvas();
  }

  init();
})();
