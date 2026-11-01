/* 墨语 · Novel Studio —— 前端逻辑（原生 JS，无框架） */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  projects: [],
  project: null,
  settings: null,
  tab: "setup",
  selected: 0,
  busy: false,
  saveTimer: null,
  chapterTimer: null,
};

/* ------------------------------------------------------------------ 基础工具 */
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("is-error", isError);
  el.classList.add("is-show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("is-show"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const data = await response.json();
      if (data && data.error) message = data.error;
    } catch (_) { /* 忽略非 JSON 错误体 */ }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

/**
 * 发起一次 SSE 请求，逐段回调。
 * @param {Function} onDelta 收到增量文本
 * @param {Function} onEvent 收到结构化事件（outline / saved / error）
 */
async function streamPost(path, payload, onDelta, onEvent) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const data = await response.json();
      if (data && data.error) message = data.error;
    } catch (_) { /* ignore */ }
    throw new Error(message);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      for (const line of block.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if (!data) continue;
        if (data === "[DONE]") return;
        let message;
        try { message = JSON.parse(data); } catch (_) { continue; }
        if (typeof message.delta === "string") onDelta(message.delta);
        else onEvent(message);
      }
    }
  }
}

const wordCount = (text) => (text || "").replace(/\s+/g, "").length;

/* ------------------------------------------------------------------ 渲染 */
function renderProjects() {
  const list = $("#project-list");
  list.innerHTML = "";
  if (!state.projects.length) {
    const empty = document.createElement("p");
    empty.className = "mode-hint";
    empty.textContent = "还没有作品";
    list.appendChild(empty);
    return;
  }
  for (const item of state.projects) {
    const button = document.createElement("button");
    button.className = "project-item" + (state.project && state.project.id === item.id ? " is-active" : "");
    button.innerHTML = `<span class="p-title"></span><span class="p-sub"></span>`;
    button.querySelector(".p-title").textContent = item.title;
    button.querySelector(".p-sub").textContent = `${item.chapter_count} 章 · ${item.word_count} 字`;
    button.addEventListener("click", () => selectProject(item.id));
    list.appendChild(button);
  }
}

function renderHeader() {
  const project = state.project;
  const has = Boolean(project);
  $("#empty-state").hidden = has;
  $("#btn-export").hidden = !has;
  $("#project-title").disabled = !has;

  if (!has) {
    ["#panel-setup", "#panel-outline", "#panel-chapters"].forEach((sel) => { $(sel).hidden = true; });
    $("#project-title").value = "";
    $("#project-meta").textContent = "";
    return;
  }

  $("#project-title").value = project.title || "";
  const chapters = project.chapters || [];
  const total = chapters.reduce((sum, chapter) => sum + wordCount(chapter.content), 0);
  $("#project-meta").textContent = `${chapters.length} 章 · ${total} 字`;

  $$(".tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.tab === state.tab));
  $("#panel-setup").hidden = state.tab !== "setup";
  $("#panel-outline").hidden = state.tab !== "outline";
  $("#panel-chapters").hidden = state.tab !== "chapters";
}

function renderSetup() {
  const setup = (state.project && state.project.setup) || {};
  $$("[data-setup]").forEach((input) => {
    input.value = setup[input.dataset.setup] || "";
  });
}

function renderOutline() {
  const box = $("#outline-list");
  box.innerHTML = "";
  const outline = (state.project && state.project.outline) || [];
  if (!outline.length) {
    const empty = document.createElement("p");
    empty.className = "outline-empty";
    empty.textContent = "还没有大纲。点右上角「生成大纲」，AI 会先给出分章骨架。";
    box.appendChild(empty);
    return;
  }
  outline.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "outline-item";
    row.innerHTML = `
      <div class="outline-index">${String(index + 1).padStart(2, "0")}</div>
      <div class="outline-fields">
        <input class="o-title" spellcheck="false" placeholder="章节标题" />
        <textarea class="o-summary" rows="2" spellcheck="false" placeholder="本章剧情要点"></textarea>
      </div>`;
    const titleInput = row.querySelector(".o-title");
    const summaryInput = row.querySelector(".o-summary");
    titleInput.value = item.title || "";
    summaryInput.value = item.summary || "";

    const touch = () => {
      item.title = titleInput.value;
      item.summary = summaryInput.value;
      scheduleProjectPatch("outline");
    };
    titleInput.addEventListener("input", touch);
    summaryInput.addEventListener("input", touch);
    titleInput.addEventListener("change", () => {
      // 标题改动同步到章节，避免两处不一致
      const chapter = (state.project.chapters || [])[index];
      if (chapter && !wordCount(chapter.content)) {
        chapter.title = titleInput.value;
        api(`/api/projects/${state.project.id}/chapters/${index}`, {
          method: "PUT",
          body: JSON.stringify({ title: chapter.title }),
        }).catch(() => {});
        renderChapterList();
      }
    });
    box.appendChild(row);
  });
}

function renderChapterList() {
  const list = $("#chapter-list");
  list.innerHTML = "";
  const chapters = (state.project && state.project.chapters) || [];
  if (!chapters.length) {
    const empty = document.createElement("p");
    empty.className = "mode-hint";
    empty.style.padding = "10px";
    empty.textContent = "还没有章节";
    list.appendChild(empty);
    return;
  }
  chapters.forEach((chapter, index) => {
    const done = wordCount(chapter.content) > 0;
    const button = document.createElement("button");
    button.className = "chapter-item" + (index === state.selected ? " is-active" : "");
    button.innerHTML = `<span class="c-title"></span><span class="c-sub${done ? " is-done" : ""}"></span>`;
    button.querySelector(".c-title").textContent = chapter.title || `第 ${index + 1} 章`;
    button.querySelector(".c-sub").textContent = done ? `${wordCount(chapter.content)} 字` : "空";
    button.addEventListener("click", () => {
      state.selected = index;
      renderChapterList();
      renderEditor();
    });
    list.appendChild(button);
  });
}

function renderEditor() {
  const chapter = (state.project && state.project.chapters && state.project.chapters[state.selected]) || null;
  const disabled = !chapter;
  $("#chapter-title").disabled = disabled;
  $("#chapter-body").disabled = disabled;
  $$("[data-write]").forEach((button) => { button.disabled = disabled || state.busy; });
  $("#btn-del-chapter").disabled = disabled;

  if (!chapter) {
    $("#chapter-title").value = "";
    $("#chapter-body").value = "";
    $("#chapter-meta").textContent = "";
    return;
  }
  $("#chapter-title").value = chapter.title || "";
  $("#chapter-body").value = chapter.content || "";
  $("#chapter-meta").textContent = `${wordCount(chapter.content)} 字 · 第 ${state.selected + 1} 章`;
}

function renderModeHint() {
  const hint = $("#mode-hint");
  if (state.settings && state.settings.has_key) {
    hint.textContent = `已连接 · ${state.settings.model}`;
    hint.classList.add("is-live");
  } else {
    hint.textContent = "演示模式 · 未配置 API Key";
    hint.classList.remove("is-live");
  }
}

function renderAll() {
  renderHeader();
  if (!state.project) {
    renderProjects();
    return;
  }
  renderSetup();
  renderOutline();
  renderChapterList();
  renderEditor();
  renderProjects();
}

/* ------------------------------------------------------------------ 数据操作 */
async function loadProjects(selectId) {
  const data = await api("/api/projects");
  state.projects = data.projects || [];
  if (!state.projects.length) {
    state.project = null;
    renderAll();
    return;
  }
  const target = selectId || (state.project && state.project.id) || state.projects[0].id;
  await selectProject(target, true);
}

async function selectProject(id, force = false) {
  if (!force && state.project && state.project.id === id) return;
  try {
    state.project = await api(`/api/projects/${id}`);
    state.selected = 0;
    state.busy = false;
    renderAll();
  } catch (error) {
    toast(error.message, true);
  }
}

async function createProject() {
  const title = prompt("给这部小说起个名字：", "未命名小说");
  if (title === null) return;
  try {
    const project = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({ title: title.trim() || "未命名小说" }),
    });
    state.project = project;
    state.selected = 0;
    state.tab = "setup";
    await loadProjects(project.id);
    $("#project-title").focus();
    $("#project-title").select();
  } catch (error) {
    toast(error.message, true);
  }
}

function scheduleProjectPatch(kind) {
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(async () => {
    if (!state.project) return;
    const payload = kind === "outline"
      ? { outline: (state.project.outline || []).map((item) => ({ ...item })) }
      : { setup: { ...(state.project.setup || {}) } };
    try {
      await api(`/api/projects/${state.project.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      const stamp = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      const el = $("#setup-state");
      if (el) el.textContent = `已保存 ${stamp}`;
      await refreshProjectList();
    } catch (error) {
      toast(error.message, true);
    }
  }, 700);
}

async function refreshProjectList() {
  try {
    const data = await api("/api/projects");
    state.projects = data.projects || [];
    renderProjects();
  } catch (_) { /* 列表刷新失败不影响主流程 */ }
}

/* ------------------------------------------------------------------ 大纲 */
async function generateOutline() {
  if (!state.project || state.busy) return;
  if ((state.project.outline || []).length &&
      !confirm("重新生成会覆盖现有大纲（已写的正文不会删除），继续？")) {
    return;
  }
  state.busy = true;
  const button = $("#btn-outline");
  button.disabled = true;
  const box = $("#outline-list");
  box.innerHTML = `<p class="outline-empty" id="outline-progress">正在生成大纲… 0 字</p>`;
  const progress = $("#outline-progress");
  let received = 0;

  try {
    await streamPost(
      `/api/projects/${state.project.id}/outline`,
      {},
      (delta) => {
        received += delta.length;
        if (progress) progress.textContent = `正在生成大纲… 已接收 ${received} 字`;
      },
      (message) => {
        if (message.event === "error") throw new Error(message.message);
        if (message.event === "outline") {
          state.project = message.project;
          state.selected = Math.min(state.selected, Math.max(0, state.project.chapters.length - 1));
          toast("大纲已生成");
        }
      }
    );
    renderAll();
    $("#setup-state").textContent = "";
  } catch (error) {
    toast(error.message, true);
    renderOutline();
  } finally {
    state.busy = false;
    button.disabled = false;
    renderEditor();
  }
}

/* ------------------------------------------------------------------ 正文 */
async function writeChapter(mode) {
  if (!state.project || state.busy) return;
  const chapter = state.project.chapters[state.selected];
  if (!chapter) return;

  if (mode === "write" && wordCount(chapter.content) > 0 &&
      !confirm("这一章已经有内容了，重新生成会覆盖，继续？")) {
    return;
  }

  state.busy = true;
  const label = { write: "生成", continue: "续写", rewrite: "重写" }[mode] || "生成";
  const status = $("#write-status");
  status.textContent = `${label}中…`;
  status.classList.add("is-busy");
  $$("[data-write]").forEach((button) => { button.disabled = true; });

  const body = $("#chapter-body");
  if (mode === "rewrite") {
    chapter.content = "";
    body.value = "";
  }
  if (mode === "continue" && chapter.content) {
    chapter.content = chapter.content.replace(/\s+$/, "") + "\n\n";
    body.value = chapter.content;
  }
  body.scrollTop = body.scrollHeight;

  try {
    await streamPost(
      `/api/projects/${state.project.id}/chapters/${state.selected}/write`,
      { mode },
      (delta) => {
        chapter.content = (chapter.content || "") + delta;
        body.value = chapter.content;
        body.scrollTop = body.scrollHeight;
        $("#chapter-meta").textContent = `${wordCount(chapter.content)} 字 · 第 ${state.selected + 1} 章`;
      },
      (message) => {
        if (message.event === "error") throw new Error(message.message);
        if (message.event === "saved") {
          chapter.content = message.chapter.content;
          chapter.title = message.chapter.title || chapter.title;
          body.value = chapter.content;
          status.textContent = `完成 · ${message.word_count} 字`;
          renderChapterList();
          refreshProjectList();
        }
      }
    );
  } catch (error) {
    status.textContent = "";
    toast(error.message, true);
  } finally {
    state.busy = false;
    status.classList.remove("is-busy");
    renderEditor();
    renderChapterList();
    setTimeout(() => {
      if (!state.busy) status.textContent = "";
    }, 4000);
  }
}

async function saveChapter(patch) {
  if (!state.project) return;
  const index = state.selected;
  try {
    await api(`/api/projects/${state.project.id}/chapters/${index}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    });
  } catch (error) {
    toast(error.message, true);
  }
}

function scheduleChapterSave() {
  clearTimeout(state.chapterTimer);
  state.chapterTimer = setTimeout(async () => {
    if (!state.project) return;
    const chapter = state.project.chapters[state.selected];
    if (!chapter) return;
    await saveChapter({ title: chapter.title, content: chapter.content });
    renderChapterList();
    refreshProjectList();
  }, 900);
}

async function addChapter() {
  if (!state.project) return;
  try {
    const project = await api(`/api/projects/${state.project.id}/chapters`, {
      method: "POST",
      body: JSON.stringify({ title: "" }),
    });
    state.project = project;
    state.selected = project.chapters.length - 1;
    renderAll();
    $("#chapter-title").focus();
  } catch (error) {
    toast(error.message, true);
  }
}

async function deleteChapter() {
  if (!state.project) return;
  if (!confirm("确定删除这一章？")) return;
  try {
    await api(`/api/projects/${state.project.id}/chapters/${state.selected}`, { method: "DELETE" });
    const fresh = await api(`/api/projects/${state.project.id}`);
    state.project = fresh;
    state.selected = Math.max(0, Math.min(state.selected, fresh.chapters.length - 1));
    renderAll();
    toast("已删除");
  } catch (error) {
    toast(error.message, true);
  }
}

/* ------------------------------------------------------------------ 设置 */
function openSettings() {
  const settings = state.settings || {};
  $("#set-base-url").value = settings.base_url || "";
  $("#set-model").value = settings.model || "";
  $("#set-api-key").value = "";
  $("#set-temperature").value = settings.temperature ?? 0.9;
  $("#set-chapter-words").value = settings.chapter_words ?? 2500;
  $("#set-outline-chapters").value = settings.outline_chapters ?? 12;
  $("#set-max-tokens").value = settings.max_tokens ?? 4096;
  $("#key-state").textContent = settings.has_key ? "当前已保存 Key" : "当前未保存 Key（演示模式）";
  $("#settings-dialog").showModal();
}

async function saveSettings() {
  const payload = {
    base_url: $("#set-base-url").value.trim(),
    model: $("#set-model").value.trim(),
    temperature: Number($("#set-temperature").value) || 0.9,
    chapter_words: Number($("#set-chapter-words").value) || 2500,
    outline_chapters: Number($("#set-outline-chapters").value) || 12,
    max_tokens: Number($("#set-max-tokens").value) || 4096,
  };
  const key = $("#set-api-key").value.trim();
  if (key) payload.api_key = key;
  try {
    state.settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    renderModeHint();
    toast(key ? "已保存，开始使用真实模型" : "设置已保存");
  } catch (error) {
    toast(error.message, true);
  }
}

/* ------------------------------------------------------------------ 事件绑定 */
function bindEvents() {
  $("#btn-new").addEventListener("click", createProject);
  $("#btn-empty-new").addEventListener("click", createProject);

  $("#project-title").addEventListener("input", (event) => {
    if (!state.project) return;
    state.project.title = event.target.value;
    scheduleProjectPatch("setup");
    refreshProjectList();
  });

  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.tab = tab.dataset.tab;
      if (history.replaceState) history.replaceState(null, "", `#${state.tab}`);
      renderHeader();
    });
  });

  $$("[data-setup]").forEach((input) => {
    input.addEventListener("input", () => {
      if (!state.project) return;
      state.project.setup[input.dataset.setup] = input.value;
      scheduleProjectPatch("setup");
    });
  });

  $("#btn-outline").addEventListener("click", generateOutline);
  $("#btn-add-chapter").addEventListener("click", addChapter);
  $("#btn-del-chapter").addEventListener("click", deleteChapter);

  $$("[data-write]").forEach((button) => {
    button.addEventListener("click", () => writeChapter(button.dataset.write));
  });

  $("#chapter-title").addEventListener("input", (event) => {
    if (!state.project) return;
    const chapter = state.project.chapters[state.selected];
    if (!chapter) return;
    chapter.title = event.target.value;
    renderChapterList();
    scheduleChapterSave();
  });

  $("#chapter-body").addEventListener("input", (event) => {
    if (!state.project) return;
    const chapter = state.project.chapters[state.selected];
    if (!chapter) return;
    chapter.content = event.target.value;
    $("#chapter-meta").textContent = `${wordCount(chapter.content)} 字 · 第 ${state.selected + 1} 章`;
    scheduleChapterSave();
  });

  $("#btn-export").addEventListener("click", () => {
    if (!state.project) return;
    window.location.href = `/api/projects/${state.project.id}/export?format=md`;
  });

  $("#btn-settings").addEventListener("click", openSettings);
  $("#btn-settings-cancel").addEventListener("click", (event) => {
    event.preventDefault();
    $("#settings-dialog").close();
  });
  $("#btn-settings-save").addEventListener("click", async (event) => {
    event.preventDefault();
    await saveSettings();
    $("#settings-dialog").close();
  });

  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (state.project) {
        saveChapter({
          title: state.project.chapters[state.selected]?.title || "",
          content: state.project.chapters[state.selected]?.content || "",
        }).then(() => toast("已保存"));
      }
    }
  });
}

/* ------------------------------------------------------------------ 启动 */
async function boot() {
  bindEvents();
  const fromHash = (location.hash || "").replace("#", "");
  if (["setup", "outline", "chapters"].includes(fromHash)) state.tab = fromHash;
  try {
    state.settings = await api("/api/settings");
  } catch (_) {
    state.settings = { has_key: false, model: "" };
  }
  renderModeHint();
  await loadProjects();
}

boot();
