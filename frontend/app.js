/**
 * No2SQL - Frontend Client Application
 * Zero-dependency, pure vanilla JavaScript
 */

(function () {
  "use strict";

  // State
  let isDataLoaded = false;
  let selectedFiles = [];
  let currentQueryToken = null;
  let currentGeneratedSQL = null;
  let lastExecutedData = null;
  let shareSampleValues = true;

  // DOM Elements - Header & Badges
  const badgeDb = document.getElementById("badge-db");
  const badgeDbDot = document.getElementById("badge-db-dot");
  const badgeDbText = document.getElementById("badge-db-text");
  const badgeLlmContainer = document.getElementById("badge-llm-container");
  const badgeLlmDot = document.getElementById("badge-llm-dot");
  const badgeLlmText = document.getElementById("badge-llm-text");
  const openSettingsBtn = document.getElementById("open-settings-btn");
  const toggleSidebarBtn = document.getElementById("toggle-sidebar-btn");

  // DOM Elements - Sidebar
  const schemaSidebar = document.getElementById("schema-sidebar");
  const schemaTree = document.getElementById("schema-tree");
  const tableCountPill = document.getElementById("table-count-pill");
  const sidebarSubhint = document.getElementById("sidebar-subhint");
  const sidebarUploadTriggerBtn = document.getElementById("sidebar-upload-trigger-btn");
  const clearDataBtn = document.getElementById("clear-data-btn");

  // DOM Elements - Upload Section
  const uploadCard = document.getElementById("upload-card");
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const selectedFilesContainer = document.getElementById("selected-files-container");
  const selectedFilesList = document.getElementById("selected-files-list");
  const uploadBtn = document.getElementById("upload-btn");
  const uploadSpinner = document.getElementById("upload-spinner");
  const uploadResultBox = document.getElementById("upload-result-box");
  const emptyStateCard = document.getElementById("empty-state-card");

  // DOM Elements - Query Workspace
  const querySection = document.getElementById("query-section");
  const questionInput = document.getElementById("question-input");
  const generateBtn = document.getElementById("generate-btn");
  const generateSpinner = document.getElementById("generate-spinner");
  const clearInputBtn = document.getElementById("clear-input-btn");
  const chipsSection = document.getElementById("chips-section");
  const exampleChipsContainer = document.getElementById("example-chips");

  // DOM Elements - Status & Result Cards
  const clarificationCard = document.getElementById("clarification-card");
  const clarificationQuestionText = document.getElementById("clarification-question-text");
  const clarificationInput = document.getElementById("clarification-input");
  const submitClarificationBtn = document.getElementById("submit-clarification-btn");

  const unsupportedCard = document.getElementById("unsupported-card");
  const unsupportedTitle = document.getElementById("unsupported-title");
  const unsupportedMessage = document.getElementById("unsupported-message");

  const resultCard = document.getElementById("result-card");
  const explanationText = document.getElementById("explanation-text");
  const assumptionsBox = document.getElementById("assumptions-box");
  const assumptionsList = document.getElementById("assumptions-list");
  const tablesPills = document.getElementById("tables-pills");
  const columnsPills = document.getElementById("columns-pills");
  const sqlCodeDisplay = document.getElementById("sql-code-display");
  const copySqlBtn = document.getElementById("copy-sql-btn");
  const runQueryBtn = document.getElementById("run-query-btn");
  const runSpinner = document.getElementById("run-spinner");

  // DOM Elements - Results Table
  const resultsCard = document.getElementById("results-card");
  const resultsCountBadge = document.getElementById("results-count-badge");
  const resultsDurationBadge = document.getElementById("results-duration-badge");
  const truncationWarning = document.getElementById("truncation-warning");
  const emptyResultsBox = document.getElementById("empty-results-box");
  const tableHead = document.getElementById("table-head");
  const tableBody = document.getElementById("table-body");
  const downloadCsvBtn = document.getElementById("download-csv-btn");

  // DOM Elements - History
  const historySection = document.getElementById("history-section");
  const historyList = document.getElementById("history-list");
  const clearHistoryBtn = document.getElementById("clear-history-btn");

  // DOM Elements - Settings Modal
  const settingsModal = document.getElementById("settings-modal");
  const closeSettingsBtn = document.getElementById("close-settings-btn");
  const modalLlmStatus = document.getElementById("modal-llm-status");
  const modalLlmModel = document.getElementById("modal-llm-model");
  const testConnectionBtn = document.getElementById("test-connection-btn");
  const shareSamplesToggle = document.getElementById("share-samples-toggle");

  // DOM Elements - Preview Modal
  const previewModal = document.getElementById("preview-modal");
  const previewModalTitle = document.getElementById("preview-modal-title");
  const closePreviewBtn = document.getElementById("close-preview-btn");
  const previewTableHead = document.getElementById("preview-table-head");
  const previewTableBody = document.getElementById("preview-table-body");

  const toastContainer = document.getElementById("toast-container");

  // Helper: Escape HTML
  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Toast Notification
  function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast ${type === "error" ? "toast-error" : type === "success" ? "toast-success" : ""}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(10px)";
      setTimeout(() => toast.remove(), 250);
    }, 4500);
  }

  // Simple SQL Syntax Highlighter
  function highlightSQL(sql) {
    const escaped = escapeHtml(sql);
    const keywords = [
      "SELECT", "FROM", "WHERE", "JOIN", "LEFT JOIN", "RIGHT JOIN", "INNER JOIN",
      "OUTER JOIN", "ON", "GROUP BY", "ORDER BY", "HAVING", "LIMIT", "AND", "OR",
      "AS", "DESC", "ASC", "NOT", "IN", "IS", "NULL", "WITH", "UNION", "ALL", "CASE",
      "WHEN", "THEN", "ELSE", "END", "EXISTS", "BETWEEN", "LIKE", "COLLATE", "NOCASE"
    ];
    const functions = ["COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND", "strftime", "date"];

    let res = escaped;
    res = res.replace(/'([^']*)'/g, '<span class="sql-string">\'$1\'</span>');
    functions.forEach(fn => {
      const reg = new RegExp(`\\b(${fn})\\b(?=\\s*\\()`, "gi");
      res = res.replace(reg, '<span class="sql-function">$1</span>');
    });
    keywords.forEach(kw => {
      const reg = new RegExp(`\\b(${kw})\\b`, "gi");
      res = res.replace(reg, '<span class="sql-keyword">$1</span>');
    });
    res = res.replace(/\b(\d+(\.\d+)?)\b/g, '<span class="sql-number">$1</span>');
    return res;
  }

  // App Initialization
  async function init() {
    loadHistory();
    setupEventListeners();
    await checkSettings();
    await checkLLMStatus(false);
    await checkDataStatus();
  }

  function setupEventListeners() {
    // Generate & Input
    generateBtn.addEventListener("click", () => handleGenerate());
    clearInputBtn.addEventListener("click", () => {
      questionInput.value = "";
      questionInput.focus();
    });
    questionInput.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        handleGenerate();
      }
    });

    // Sidebar & View
    toggleSidebarBtn.addEventListener("click", () => {
      schemaSidebar.classList.toggle("collapsed");
    });
    sidebarUploadTriggerBtn.addEventListener("click", () => {
      uploadCard.classList.remove("hidden");
      uploadCard.scrollIntoView({ behavior: "smooth" });
    });
    clearDataBtn.addEventListener("click", handleClearAllData);

    // SQL actions
    copySqlBtn.addEventListener("click", handleCopySQL);
    runQueryBtn.addEventListener("click", handleRunQuery);
    downloadCsvBtn.addEventListener("click", handleDownloadCSV);
    clearHistoryBtn.addEventListener("click", handleClearHistory);

    // Clarification
    submitClarificationBtn.addEventListener("click", () => {
      const clarification = clarificationInput.value.trim();
      if (!clarification) return;
      const originalQ = questionInput.value.trim();
      questionInput.value = `${originalQ} (${clarification})`;
      clarificationCard.classList.add("hidden");
      handleGenerate();
    });

    // Upload Drag & Drop
    dropZone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", handleFileSelect);

    ["dragenter", "dragover"].forEach(eventName => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropZone.classList.add("drag-over");
      });
    });

    ["dragleave", "drop"].forEach(eventName => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropZone.classList.remove("drag-over");
      });
    });

    dropZone.addEventListener("drop", (e) => {
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        addFiles(Array.from(e.dataTransfer.files));
      }
    });

    uploadBtn.addEventListener("click", handleUploadFiles);

    // Settings Modal
    openSettingsBtn.addEventListener("click", () => {
      settingsModal.classList.remove("hidden");
    });
    closeSettingsBtn.addEventListener("click", () => settingsModal.classList.add("hidden"));
    testConnectionBtn.addEventListener("click", () => checkLLMStatus(true));
    shareSamplesToggle.addEventListener("change", handleToggleShareSamples);

    // Preview Modal
    closePreviewBtn.addEventListener("click", () => previewModal.classList.add("hidden"));
  }

  // Check Settings
  async function checkSettings() {
    try {
      const res = await fetch("/api/settings");
      if (res.ok) {
        const data = await res.json();
        shareSampleValues = Boolean(data.share_sample_values);
        shareSamplesToggle.checked = shareSampleValues;
        modalLlmModel.textContent = data.model || "gemini-3.8-flash";
      }
    } catch {}
  }

  async function handleToggleShareSamples() {
    shareSampleValues = shareSamplesToggle.checked;
    try {
      await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ share_sample_values: shareSampleValues }),
      });
      showToast(shareSampleValues ? "Sample values sharing enabled." : "Sample values sharing disabled.", "info");
    } catch {}
  }

  // LLM Status Check
  async function checkLLMStatus(refresh = false) {
    try {
      modalLlmStatus.textContent = "Checking...";
      const res = await fetch(`/api/llm/status?refresh=${refresh}`);
      if (!res.ok) throw new Error("Status check failed");
      const data = await res.json();

      modalLlmModel.textContent = data.model || "gemini-3.8-flash";

      if (data.status === "connected") {
        badgeLlmDot.className = "badge-dot dot-green";
        badgeLlmText.textContent = "Gemini: connected";
        modalLlmStatus.innerHTML = `<span style="color: #34d399;">Connected (${data.model})</span>`;
        if (refresh) showToast("Gemini connection test successful!", "success");
      } else if (data.status === "missing_key") {
        badgeLlmDot.className = "badge-dot dot-red";
        badgeLlmText.textContent = "Gemini: key missing in .env";
        modalLlmStatus.innerHTML = `<span style="color: #f87171;">Key missing in .env</span>`;
        if (refresh) showToast(data.message, "error");
      } else {
        badgeLlmDot.className = "badge-dot dot-amber";
        badgeLlmText.textContent = "Gemini: error";
        modalLlmStatus.innerHTML = `<span style="color: #fbbf24;">${escapeHtml(data.message)}</span>`;
        if (refresh) showToast(data.message, "error");
      }
    } catch (e) {
      badgeLlmDot.className = "badge-dot dot-amber";
      badgeLlmText.textContent = "Gemini: error";
      modalLlmStatus.innerHTML = `<span style="color: #fbbf24;">Connection error</span>`;
    }
  }

  // Data Status & Workspace Check
  async function checkDataStatus() {
    try {
      const res = await fetch("/api/data/status");
      if (!res.ok) throw new Error("Status check failed");
      const status = await res.json();

      isDataLoaded = Boolean(status.is_loaded);

      if (isDataLoaded) {
        badgeDbDot.className = "badge-dot dot-green";
        badgeDbText.textContent = `workspace.db (${status.table_count} table${status.table_count === 1 ? "" : "s"}, ${status.total_rows} rows)`;
        tableCountPill.textContent = `${status.table_count} Tables`;
        sidebarSubhint.textContent = "Click a table to inspect columns, or preview rows.";

        emptyStateCard.classList.add("hidden");
        querySection.classList.remove("hidden");
        historySection.classList.remove("hidden");

        await loadSchemaTree();
        loadSuggestions();
      } else {
        badgeDbDot.className = "badge-dot dot-gray";
        badgeDbText.textContent = "No data loaded";
        tableCountPill.textContent = "0 Tables";
        sidebarSubhint.textContent = "Upload files to create database tables.";

        emptyStateCard.classList.remove("hidden");
        querySection.classList.add("hidden");
        resultCard.classList.add("hidden");
        resultsCard.classList.add("hidden");
        chipsSection.classList.add("hidden");
        historySection.classList.add("hidden");

        schemaTree.innerHTML = `
          <div class="empty-schema-state">
            No tables loaded yet. Upload CSV, Excel, JSON or SQLite files above.
          </div>
        `;
      }
    } catch (err) {
      console.warn("Could not load data status:", err);
    }
  }

  // Load Schema Tree for Sidebar
  async function loadSchemaTree() {
    try {
      const res = await fetch("/api/schema");
      if (!res.ok) throw new Error("Failed to load schema");
      const schema = await res.json();
      renderSchemaTree(schema);
    } catch (err) {
      schemaTree.innerHTML = `<div class="empty-schema-state" style="color:#ef4444;">Failed to read database schema.</div>`;
    }
  }

  function renderSchemaTree(schema) {
    schemaTree.innerHTML = "";
    const tables = schema.tables || {};

    Object.keys(tables).forEach((tableName, idx) => {
      const table = tables[tableName];
      const item = document.createElement("div");
      item.className = `schema-table-item ${idx === 0 ? "expanded" : ""}`;

      const colCount = (table.columns || []).length;

      const header = document.createElement("div");
      header.className = "schema-table-header";
      header.innerHTML = `
        <span class="table-name">${escapeHtml(table.name)}</span>
        <span class="table-badge">${table.row_count} rows &bull; ${colCount} cols</span>
      `;
      header.addEventListener("click", () => {
        item.classList.toggle("expanded");
      });

      const body = document.createElement("div");
      body.className = "schema-table-body";

      // Preview button
      const actionsRow = document.createElement("div");
      actionsRow.className = "table-actions-row";
      const previewBtn = document.createElement("button");
      previewBtn.className = "btn btn-sm btn-secondary";
      previewBtn.textContent = "Preview First 10 Rows";
      previewBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openTablePreview(table.name);
      });
      actionsRow.appendChild(previewBtn);
      body.appendChild(actionsRow);

      // Columns list
      (table.columns || []).forEach(col => {
        const colDiv = document.createElement("div");
        colDiv.className = "col-item";
        const pkBadge = col.primary_key ? `<span class="col-pk">PK</span>` : "";
        const origHint = col.original_name && col.original_name !== col.name
          ? `<span class="col-orig-hint" title="Original header: ${escapeHtml(col.original_name)}">(${escapeHtml(col.original_name)})</span>`
          : "";

        colDiv.innerHTML = `
          <span class="col-name">${escapeHtml(col.name)}${pkBadge}${origHint}</span>
          <span class="col-type">${escapeHtml(col.type)}</span>
        `;
        body.appendChild(colDiv);
      });

      item.appendChild(header);
      item.appendChild(body);
      schemaTree.appendChild(item);
    });
  }

  // Open Table Preview Modal
  async function openTablePreview(tableName) {
    previewModalTitle.textContent = `Table Preview: ${tableName} (First 10 Rows)`;
    previewTableHead.innerHTML = "<tr><th>Loading preview...</th></tr>";
    previewTableBody.innerHTML = "";
    previewModal.classList.remove("hidden");

    try {
      const res = await fetch(`/api/data/preview?table=${encodeURIComponent(tableName)}&limit=10`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to load table preview");
      }
      const data = await res.json();
      const cols = data.columns || [];
      const origCols = data.original_columns || [];
      const rows = data.rows || [];

      previewTableHead.innerHTML = `<tr>${cols.map((c, i) => {
        const orig = origCols[i] && origCols[i] !== c ? `<br><small style="color:#94a3b8; font-weight:normal;">(${escapeHtml(origCols[i])})</small>` : "";
        return `<th>${escapeHtml(c)}${orig}</th>`;
      }).join("")}</tr>`;

      if (rows.length === 0) {
        previewTableBody.innerHTML = `<tr><td colspan="${cols.length || 1}" style="text-align:center; color:#9ca3af;">Table is empty.</td></tr>`;
      } else {
        previewTableBody.innerHTML = rows.map(r => `<tr>${r.map(v => `<td>${escapeHtml(v)}</td>`).join("")}</tr>`).join("");
      }
    } catch (err) {
      previewTableHead.innerHTML = `<tr><th style="color:#ef4444;">${escapeHtml(err.message)}</th></tr>`;
    }
  }

  // File Selection & Drag-and-Drop Handling
  function handleFileSelect(e) {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(Array.from(e.target.files));
      e.target.value = "";
    }
  }

  function addFiles(files) {
    files.forEach(f => {
      if (!selectedFiles.some(existing => existing.name === f.name && existing.size === f.size)) {
        selectedFiles.push(f);
      }
    });
    renderSelectedFiles();
  }

  function removeFile(index) {
    selectedFiles.splice(index, 1);
    renderSelectedFiles();
  }

  function renderSelectedFiles() {
    selectedFilesList.innerHTML = "";
    if (selectedFiles.length === 0) {
      selectedFilesContainer.classList.add("hidden");
      uploadBtn.disabled = true;
      return;
    }

    selectedFilesContainer.classList.remove("hidden");
    uploadBtn.disabled = false;

    selectedFiles.forEach((file, idx) => {
      const li = document.createElement("li");
      li.className = "file-list-item";
      const sizeKb = (file.size / 1024).toFixed(1);
      li.innerHTML = `
        <span><strong>${escapeHtml(file.name)}</strong> (${sizeKb} KB)</span>
        <button class="file-remove-btn" title="Remove file">&times;</button>
      `;
      li.querySelector(".file-remove-btn").addEventListener("click", () => removeFile(idx));
      selectedFilesList.appendChild(li);
    });
  }

  // Upload Files Action
  async function handleUploadFiles() {
    if (selectedFiles.length === 0) return;

    uploadBtn.disabled = true;
    uploadSpinner.classList.remove("hidden");
    uploadResultBox.classList.add("hidden");
    uploadResultBox.innerHTML = "";

    const mode = document.querySelector('input[name="upload-mode"]:checked').value;
    const formData = new FormData();
    formData.append("mode", mode);
    selectedFiles.forEach(f => formData.append("files", f));

    try {
      const res = await fetch("/api/data/upload", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Upload failed.");
      }

      const result = await res.json();
      const tables = result.tables || [];
      const warnings = result.warnings || [];

      let html = `<div class="upload-success-box"><strong>Data loaded successfully!</strong> Created ${tables.length} table${tables.length === 1 ? "" : "s"}: `;
      html += tables.map(t => `<code>${escapeHtml(t.name)}</code> (${t.row_count} rows)`).join(", ");
      html += `</div>`;

      if (warnings.length > 0) {
        html += `<div class="upload-warning-box"><strong>Notice:</strong><ul>${warnings.map(w => `<li>${escapeHtml(w)}</li>`).join("")}</ul></div>`;
      }

      uploadResultBox.innerHTML = html;
      uploadResultBox.classList.remove("hidden");

      selectedFiles = [];
      renderSelectedFiles();

      showToast("Data uploaded and database built successfully!", "success");
      await checkDataStatus();
    } catch (err) {
      uploadResultBox.innerHTML = `<div class="card-refusal" style="padding:10px 14px; border-radius:4px;"><strong>Upload error:</strong> ${escapeHtml(err.message)}</div>`;
      uploadResultBox.classList.remove("hidden");
      showToast(err.message, "error");
    } finally {
      uploadBtn.disabled = false;
      uploadSpinner.classList.add("hidden");
    }
  }

  // Clear All Data
  async function handleClearAllData() {
    const confirmClear = confirm("Are you sure you want to clear all data from the workspace database? This action cannot be undone.");
    if (!confirmClear) return;

    clearDataBtn.disabled = true;
    try {
      const res = await fetch("/api/data", { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to clear data");
      showToast("All workspace data cleared.", "info");
      await checkDataStatus();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      clearDataBtn.disabled = false;
    }
  }

  // Dynamic Question Suggestions
  async function loadSuggestions() {
    chipsSection.classList.add("hidden");
    exampleChipsContainer.innerHTML = "";

    try {
      const res = await fetch("/api/data/suggestions");
      if (!res.ok) return;
      const data = await res.json();
      const questions = data.questions || [];

      if (questions.length > 0) {
        exampleChipsContainer.innerHTML = "";
        questions.forEach(q => {
          const chip = document.createElement("button");
          chip.className = "chip";
          chip.textContent = q;
          chip.addEventListener("click", () => {
            questionInput.value = q;
            questionInput.focus();
            handleGenerate();
          });
          exampleChipsContainer.appendChild(chip);
        });
        chipsSection.classList.remove("hidden");
      }
    } catch {}
  }

  // Handle Query Generation
  async function handleGenerate() {
    const question = questionInput.value.trim();
    if (!question) {
      showToast("Please enter a question first.", "info");
      questionInput.focus();
      return;
    }

    if (!isDataLoaded) {
      showToast("Please upload your data first.", "info");
      uploadCard.scrollIntoView({ behavior: "smooth" });
      return;
    }

    // Hide cards
    clarificationCard.classList.add("hidden");
    unsupportedCard.classList.add("hidden");
    resultCard.classList.add("hidden");
    resultsCard.classList.add("hidden");

    // Loading state
    generateBtn.disabled = true;
    generateSpinner.classList.remove("hidden");

    try {
      const res = await fetch("/api/query/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, share_sample_values: shareSampleValues })
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Server error generating query.");
      }

      const data = await res.json();
      addToHistory(question);

      if (data.status === "clarification_needed") {
        clarificationQuestionText.textContent = data.clarification_question || "Please provide further details to narrow down your request.";
        clarificationInput.value = "";
        clarificationCard.classList.remove("hidden");
        clarificationInput.focus();
      } else if (data.status === "unsupported") {
        unsupportedTitle.textContent = "Request Not Executable";
        unsupportedMessage.textContent = data.explanation || "This operation is not supported by read-only rules or the requested data does not exist in the uploaded schema.";
        unsupportedCard.classList.remove("hidden");
      } else if (data.status === "ok" && data.sql) {
        currentQueryToken = data.query_token;
        currentGeneratedSQL = data.sql;

        explanationText.textContent = data.explanation;

        // Assumptions
        if (data.assumptions && data.assumptions.length > 0) {
          assumptionsList.innerHTML = data.assumptions.map(a => `<li>${escapeHtml(a)}</li>`).join("");
          assumptionsBox.classList.remove("hidden");
        } else {
          assumptionsBox.classList.add("hidden");
        }

        // Tables pills
        tablesPills.innerHTML = (data.tables_used || []).map(t => `<span class="tag-pill">${escapeHtml(t)}</span>`).join("");
        columnsPills.innerHTML = (data.columns_used || []).map(c => `<span class="tag-pill">${escapeHtml(c)}</span>`).join("");

        // Highlighted SQL
        sqlCodeDisplay.innerHTML = highlightSQL(data.sql);

        // Run query button state
        runQueryBtn.disabled = !currentQueryToken;

        resultCard.classList.remove("hidden");
      } else {
        showToast("Unexpected response format from server.", "error");
      }
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      generateBtn.disabled = false;
      generateSpinner.classList.add("hidden");
    }
  }

  // Handle Run Query
  async function handleRunQuery() {
    if (!currentQueryToken) {
      showToast("No validated query token available.", "error");
      return;
    }

    runQueryBtn.disabled = true;
    runSpinner.classList.remove("hidden");
    resultsCard.classList.add("hidden");

    try {
      const res = await fetch("/api/query/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query_token: currentQueryToken })
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Database query execution failed.");
      }

      const data = await res.json();
      lastExecutedData = data;
      renderResults(data);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      runQueryBtn.disabled = false;
      runSpinner.classList.add("hidden");
    }
  }

  // Render Execution Results Table
  function renderResults(data) {
    resultsCountBadge.textContent = `${data.row_count} row${data.row_count === 1 ? "" : "s"}`;
    resultsDurationBadge.textContent = `${data.duration_ms} ms`;

    if (data.truncated) {
      truncationWarning.classList.remove("hidden");
    } else {
      truncationWarning.classList.add("hidden");
    }

    const cols = data.columns || [];
    const rows = data.rows || [];

    if (rows.length === 0) {
      emptyResultsBox.classList.remove("hidden");
      tableHead.innerHTML = "";
      tableBody.innerHTML = "";
    } else {
      emptyResultsBox.classList.add("hidden");
      tableHead.innerHTML = `<tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
      tableBody.innerHTML = rows.map(r => `<tr>${r.map(val => `<td>${escapeHtml(val)}</td>`).join("")}</tr>`).join("");
    }

    resultsCard.classList.remove("hidden");
    resultsCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // Copy SQL to Clipboard
  function handleCopySQL() {
    if (!currentGeneratedSQL) return;
    navigator.clipboard.writeText(currentGeneratedSQL).then(() => {
      const originalText = copySqlBtn.textContent;
      copySqlBtn.textContent = "Copied!";
      copySqlBtn.classList.add("btn-primary");
      setTimeout(() => {
        copySqlBtn.textContent = originalText;
        copySqlBtn.classList.remove("btn-primary");
      }, 1800);
    }).catch(() => {
      showToast("Failed to copy SQL to clipboard.", "error");
    });
  }

  // Download CSV
  function handleDownloadCSV() {
    if (!lastExecutedData || !lastExecutedData.rows || lastExecutedData.rows.length === 0) {
      showToast("No data rows available to export.", "info");
      return;
    }

    const cols = lastExecutedData.columns || [];
    const rows = lastExecutedData.rows || [];

    const csvLines = [];
    csvLines.push(cols.map(c => `"${String(c).replace(/"/g, '""')}"`).join(","));

    rows.forEach(row => {
      const line = row.map(cell => {
        const strVal = cell === null || cell === undefined ? "" : String(cell);
        return `"${strVal.replace(/"/g, '""')}"`;
      }).join(",");
      csvLines.push(line);
    });

    const csvContent = csvLines.join("\r\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `no2sql_export_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    showToast("CSV export downloaded successfully.", "success");
  }

  // Session History Management
  function loadHistory() {
    try {
      const raw = localStorage.getItem("no2sql_history");
      const list = raw ? JSON.parse(raw) : [];
      renderHistory(list);
    } catch {
      renderHistory([]);
    }
  }

  function addToHistory(question) {
    try {
      let list = [];
      const raw = localStorage.getItem("no2sql_history");
      if (raw) list = JSON.parse(raw);

      list = list.filter(q => q.toLowerCase() !== question.toLowerCase());
      list.unshift(question);
      list = list.slice(0, 10);

      localStorage.setItem("no2sql_history", JSON.stringify(list));
      renderHistory(list);
    } catch (e) {
      console.warn("Could not save history to localStorage", e);
    }
  }

  function renderHistory(items) {
    historyList.innerHTML = "";
    if (!items || items.length === 0) {
      historyList.innerHTML = `<li class="history-empty">No recent questions yet.</li>`;
      return;
    }

    items.forEach(q => {
      const li = document.createElement("li");
      li.className = "history-item";
      li.textContent = q;
      li.title = `Click to load: "${q}"`;
      li.addEventListener("click", () => {
        questionInput.value = q;
        questionInput.focus();
        handleGenerate();
      });
      historyList.appendChild(li);
    });
  }

  function handleClearHistory() {
    try {
      localStorage.removeItem("no2sql_history");
    } catch {}
    renderHistory([]);
    showToast("Session history cleared.", "info");
  }

  // Run on page load
  document.addEventListener("DOMContentLoaded", init);
})();
