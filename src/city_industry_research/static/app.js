const state = {
  currentJobId: null,
  pollTimer: null,
};

const qs = (selector) => document.querySelector(selector);
const researchForm = qs("#researchForm");
const emailForm = qs("#emailForm");
const docsForm = qs("#docsForm");
const systemStatus = qs("#systemStatus");
const jobBadge = qs("#jobBadge");
const logList = qs("#logList");
const validationList = qs("#validationList");
const validationCount = qs("#validationCount");
const reportPreview = qs("#reportPreview");
const reportPath = qs("#reportPath");
const downloadLink = qs("#downloadLink");
const exportStatus = qs("#exportStatus");

function setYearDefault() {
  const year = researchForm.elements.year;
  year.value = new Date().getFullYear();
}

async function loadStatus() {
  const response = await fetch("/api/status");
  const data = await response.json();
  const parts = [];
  parts.push(data.has_openai_key ? "OpenAI 已配置" : "未配置 OpenAI");
  parts.push(data.smtp_configured ? "SMTP 已配置" : "邮件需授权");
  if (data.default_model) parts.push(data.default_model);
  systemStatus.textContent = parts.join(" · ");
}

function setFormsEnabled(enabled) {
  emailForm.querySelector("button").disabled = !enabled;
  docsForm.querySelector("button").disabled = !enabled;
}

function setLogs(logs) {
  logList.innerHTML = "";
  logs.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    logList.appendChild(li);
  });
}

function setValidationEvents(events) {
  validationCount.textContent = `${events.length} 条记录`;
  validationList.innerHTML = "";
  if (!events.length) {
    const empty = document.createElement("div");
    empty.className = "validation-empty";
    empty.textContent = "等待任务开始。";
    validationList.appendChild(empty);
    return;
  }
  events.forEach((event) => {
    const item = document.createElement("div");
    item.className = "validation-item";

    const time = document.createElement("div");
    time.className = "validation-time";
    time.textContent = event.time || "";

    const stage = document.createElement("div");
    stage.className = "validation-stage";
    stage.textContent = event.stage || "";

    const status = document.createElement("div");
    const normalizedStatus = String(event.status || "").toLowerCase();
    status.className = `validation-status ${normalizedStatus}`;
    status.textContent = event.status || "";

    const detail = document.createElement("div");
    detail.className = "validation-detail";
    detail.textContent = event.detail || "";
    const metaText = compactMetadata(event.metadata || {});
    if (metaText) {
      const meta = document.createElement("div");
      meta.className = "validation-meta";
      meta.textContent = metaText;
      detail.appendChild(meta);
    }

    item.append(time, stage, status, detail);
    validationList.appendChild(item);
  });
  validationList.scrollTop = validationList.scrollHeight;
}

function compactMetadata(metadata) {
  const entries = Object.entries(metadata).filter(([, value]) => {
    if (value === null || value === undefined || value === "") return false;
    if (Array.isArray(value) && !value.length) return false;
    if (typeof value === "object" && !Array.isArray(value) && !Object.keys(value).length) return false;
    return true;
  });
  if (!entries.length) return "";
  return entries
    .slice(0, 6)
    .map(([key, value]) => {
      const rendered = typeof value === "object" ? JSON.stringify(value) : String(value);
      return `${key}: ${rendered}`;
    })
    .join(" · ");
}

function setJob(job) {
  state.currentJobId = job.id;
  jobBadge.textContent = `${job.status} · ${job.id}`;
  setLogs(job.logs || []);
  setValidationEvents(job.validation_events || []);
  reportPath.textContent = job.report_path || "";
  if (job.report_preview) {
    reportPreview.textContent = job.report_preview;
  }
  if (job.error) {
    reportPreview.textContent = job.error;
    reportPreview.classList.add("is-error");
  } else {
    reportPreview.classList.remove("is-error");
  }
  if (job.has_report) {
    downloadLink.href = `/api/jobs/${job.id}/report?download=1`;
    downloadLink.classList.remove("hidden");
    setFormsEnabled(true);
  } else {
    downloadLink.classList.add("hidden");
    setFormsEnabled(false);
  }
  if (job.export_requests && job.export_requests.length) {
    const latest = job.export_requests[job.export_requests.length - 1];
    exportStatus.textContent = `${latest.type} · ${latest.status}\n${latest.request_path || latest.to || latest.title || ""}`;
  }
}

async function pollJob() {
  if (!state.currentJobId) return;
  const response = await fetch(`/api/jobs/${state.currentJobId}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "任务读取失败");
  setJob(data.job);
  if (["done", "error"].includes(data.job.status)) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

researchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(researchForm);
  const payload = {
    province: form.get("province"),
    city: form.get("city"),
    year: Number(form.get("year")),
    model: form.get("model"),
    mode: form.get("mode"),
    query_limit: Number(form.get("query_limit")) || 48,
    max_sources: Number(form.get("max_sources")) || 120,
    use_model_web_search: form.get("use_model_web_search") === "on",
    source_urls: form.get("source_urls"),
  };
  reportPreview.textContent = "任务已提交，正在准备研究。";
  logList.innerHTML = "";
  setValidationEvents([]);
  exportStatus.textContent = "等待报告生成。";
  setFormsEnabled(false);

  const response = await fetch("/api/research", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    reportPreview.textContent = data.error || "任务创建失败";
    reportPreview.classList.add("is-error");
    return;
  }
  setJob(data.job);
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(pollJob, 2000);
});

emailForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.currentJobId) return;
  const form = new FormData(emailForm);
  exportStatus.textContent = "正在创建邮件导出请求。";
  const response = await fetch(`/api/jobs/${state.currentJobId}/export/email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      to: form.get("to"),
      subject: form.get("subject"),
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    exportStatus.textContent = data.error || "邮件导出失败";
    return;
  }
  setJob(data.job);
});

docsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.currentJobId) return;
  const form = new FormData(docsForm);
  exportStatus.textContent = "正在创建 Google Docs 导出请求。";
  const response = await fetch(`/api/jobs/${state.currentJobId}/export/google-docs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: form.get("title"),
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    exportStatus.textContent = data.error || "Google Docs 导出失败";
    return;
  }
  setJob(data.job);
});

setYearDefault();
loadStatus().catch(() => {
  systemStatus.textContent = "环境状态读取失败";
});
