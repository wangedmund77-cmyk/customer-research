const state = {
  project: null,
  framework: [],
  selectedModuleIndex: 0,
  selectedFrameworkIndex: 0,
};

const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => Array.from(document.querySelectorAll(selector));

const customerForm = qs("#customerForm");
const customerSelect = qs("#customerSelect");
const moduleList = qs("#moduleList");
const frameworkCount = qs("#frameworkCount");
const frameworkDetail = qs("#frameworkDetail");
const summaryBoard = qs("#summaryBoard");
const dashboardBoard = qs("#dashboardBoard");
const supplementBoard = qs("#supplementBoard");
const supplementCount = qs("#supplementCount");
const sourceBoard = qs("#sourceBoard");
const sourceCount = qs("#sourceCount");
const dashboardDownloadReport = qs("#dashboardDownloadReport");
const dashboardDownloadWord = qs("#dashboardDownloadWord");

async function loadStatus() {
  const response = await fetch("/api/status");
  const data = await response.json();
  state.framework = data.framework || [];
  renderModuleList(data.framework || []);
  await loadSelectedCustomer();
}

function renderModuleList(framework) {
  moduleList.innerHTML = "";
  const totalFields = framework.reduce((total, item) => total + Number(item.field_count || 0), 0);
  frameworkCount.textContent = `${framework.length} 模块 · ${totalFields} 字段`;
  if (state.selectedFrameworkIndex >= framework.length) {
    state.selectedFrameworkIndex = 0;
  }
  framework.forEach((item, index) => {
    const li = document.createElement("li");
    li.classList.toggle("is-active", index === state.selectedFrameworkIndex);
    li.dataset.frameworkIndex = String(index);
    li.innerHTML = `
      <button type="button">
        <span>${escapeHtml(cleanModuleName(item.name))}</span>
        <strong>${Number(item.field_count || 0)} 字段</strong>
      </button>
    `;
    moduleList.appendChild(li);
  });
  renderFrameworkDetail(framework[state.selectedFrameworkIndex] || framework[0]);
}

moduleList.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const tab = event.target.closest("[data-framework-index]");
  if (!tab) return;
  state.selectedFrameworkIndex = Number(tab.dataset.frameworkIndex || 0);
  renderModuleList(state.framework || []);
  requestAnimationFrame(() => {
    frameworkDetail?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
});

function renderFrameworkDetail(module) {
  if (!frameworkDetail) return;
  if (!module) {
    frameworkDetail.classList.add("empty-state");
    frameworkDetail.textContent = "暂无框架字段。";
    return;
  }
  const categories = module.categories || [];
  frameworkDetail.classList.remove("empty-state");
  frameworkDetail.innerHTML = `
    <section class="framework-detail-panel">
      <div class="framework-detail-header">
        <div>
          <p class="eyebrow">Excel Framework Detail</p>
          <h3>${escapeHtml(cleanModuleName(module.name || module.module))}</h3>
        </div>
        <span>${Number(module.field_count || 0)} 字段 · ${categories.length} 类别</span>
      </div>
      <div class="framework-category-grid">
        ${categories.map(renderFrameworkCategory).join("")}
      </div>
    </section>
  `;
}

function renderFrameworkCategory(category) {
  const fields = category.fields || [];
  return `
    <article class="framework-category-card">
      <div class="framework-category-head">
        <h4>${escapeHtml(category.name)}</h4>
        <span>${Number(category.field_count || fields.length)} 字段</span>
      </div>
      <div class="framework-field-table">
        <div class="framework-field-row is-head">
          <strong>具体</strong>
          <span>说明</span>
        </div>
        ${fields
          .map(
            (field) => `
              <div class="framework-field-row">
                <strong>${escapeHtml(field.field)}</strong>
                <span>${escapeHtml(field.description)}</span>
              </div>
            `,
          )
          .join("")}
      </div>
    </article>
  `;
}

qsa(".view-tab").forEach((button) => {
  button.addEventListener("click", () => {
    const view = button.dataset.view;
    qsa(".view-tab").forEach((item) => item.classList.toggle("is-active", item === button));
    qs("#summaryView").classList.toggle("is-hidden", view !== "summary");
    qs("#dashboardView").classList.toggle("is-hidden", view !== "dashboard");
    qs("#supplementView").classList.toggle("is-hidden", view !== "supplement");
    qs("#sourceView").classList.toggle("is-hidden", view !== "sources");
    qs("#frameworkView").classList.toggle("is-hidden", view !== "framework");
  });
});

customerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  loadSelectedCustomer();
});

customerSelect.addEventListener("change", () => {
  loadSelectedCustomer();
});

dashboardBoard.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const card = event.target.closest(".module-overview-card");
  if (!card) return;
  state.selectedModuleIndex = Number(card.dataset.moduleIndex || 0);
  if (!state.project) return;
  renderDashboard(state.project);
  requestAnimationFrame(() => {
    qs("#selectedModulePanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

async function loadSelectedCustomer() {
  const customer = customerSelect.value;
  if (!customer) return;
  state.selectedModuleIndex = 0;
  if (summaryBoard) {
    summaryBoard.classList.add("empty-state");
    summaryBoard.textContent = "正在生成企业摘要...";
  }
  dashboardBoard.classList.add("empty-state");
  dashboardBoard.textContent = "正在加载企业 360 洞察画像...";
  if (supplementBoard) {
    supplementBoard.classList.add("empty-state");
    supplementBoard.textContent = "正在整理信息补充清单...";
  }
  if (sourceBoard) {
    sourceBoard.classList.add("empty-state");
    sourceBoard.textContent = "正在整理数据来源...";
  }

  const response = await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      customer,
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    dashboardBoard.textContent = data.error || "加载失败";
    return;
  }
  setProject(data.project);
}

function setProject(project) {
  state.project = project;
  setLinks(project);
  renderSummaryPage(project);
  renderDashboard(project);
  renderSupplementPlan(project);
  renderReferenceSources(project);
}

function setLinks(project) {
  const reportHref = `/api/projects/${project.id}/report?download=1`;
  const wordHref = `/api/projects/${project.id}/report-docx?download=1`;
  toggleLink(dashboardDownloadReport, project.has_report, reportHref);
  toggleLink(dashboardDownloadWord, project.has_report, wordHref);
}

function toggleLink(link, enabled, href) {
  if (!link) return;
  if (enabled) {
    link.href = href;
    link.classList.remove("is-disabled");
  } else {
    link.href = "#";
    link.classList.add("is-disabled");
  }
}

function renderSummaryPage(project) {
  if (!summaryBoard) return;
  const summary = project.insight_dashboard?.competitor_summary || {};
  summaryBoard.classList.remove("empty-state");
  summaryBoard.innerHTML = `
    <section class="executive-summary-shell">
      <article class="executive-hero-card">
        <div>
          <p class="eyebrow">9-Module Executive Summary</p>
          <h3>${escapeHtml(summary.title || "企业摘要")}</h3>
          <p>${escapeHtml(summary.one_sentence || "")}</p>
        </div>
        ${renderSummaryAudience(summary)}
      </article>

      ${renderKeyAnalysis(summary.key_analysis || [])}
      ${renderSubstitutionChain(summary.substitution_chain || [], summary)}
      ${renderModuleTakeaways(summary.module_takeaways || [])}
      ${renderExecutiveActions(summary.actions || [], summary)}
      ${renderExecutiveWatchlist(summary.watchlist || [])}
    </section>
  `;
}

function renderSummaryAudience(summary = {}) {
  const audiences = (summary.key_analysis || []).map((item) => item.audience).filter(Boolean);
  if (!audiences.length) return "";
  return `
    <div class="executive-hero-audience" aria-label="摘要适用对象">
      <span>适用对象</span>
      <div>
        ${audiences.map((audience) => `<b>${escapeHtml(audience)}</b>`).join("")}
      </div>
    </div>
  `;
}

function renderKeyAnalysis(items) {
  if (!items.length) return "";
  return `
    <section class="executive-section">
      <div class="section-row">
        <div>
          <p class="eyebrow">Key Analysis</p>
          <h3>关键分析</h3>
        </div>
        <span>盘厂客户经理 · 销售 · 战略部门</span>
      </div>
      <div class="key-analysis-grid">
        ${items
          .map(
            (item) => `
              <article class="key-analysis-card">
                <div>
                  <span>${escapeHtml(item.audience || "")}</span>
                  <strong>${escapeHtml(item.title || "")}</strong>
                </div>
                <p>${escapeHtml(item.analysis || "")}</p>
                <dl>
                  <div>
                    <dt>重点动作</dt>
                    <dd>${escapeHtml(item.what_to_do || "")}</dd>
                  </div>
                  <div>
                    <dt>关注风险</dt>
                    <dd>${escapeHtml(item.risk_or_watch || "")}</dd>
                  </div>
                </dl>
                <small>${renderSourceIds(item.source_ids || [])}</small>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderSubstitutionChain(items, summary = {}) {
  if (!items.length) return "";
  return `
    <section class="executive-section">
      <div class="section-row">
        <div>
          <p class="eyebrow">${escapeHtml(summary.chain_eyebrow || "Substitution Chain")}</p>
          <h3>${escapeHtml(summary.chain_heading || "竞品替代链路")}</h3>
        </div>
        <span>${escapeHtml(summary.chain_badge || "施耐德防守视角")}</span>
      </div>
      <div class="substitution-chain">
        ${items
          .map(
            (item) => `
              <article class="substitution-step">
                <b>${escapeHtml(item.step)}</b>
                <strong>${escapeHtml(item.question)}</strong>
                <p>${escapeHtml(item.insight)}</p>
                <small>${renderSourceIds(item.source_ids || [])}</small>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderModuleTakeaways(items) {
  if (!items.length) return "";
  return `
    <section class="executive-section">
      <div class="section-row">
        <div>
          <p class="eyebrow">Enterprise Insight Modules</p>
          <h3>企业洞察9大模块摘要</h3>
        </div>
        <span>盘厂客户经理 · 销售 · 战略部门</span>
      </div>
      <div class="module-takeaway-grid">
        ${items
          .map(
            (item) => `
              <article class="module-takeaway-card">
                <div>
                  <span>${escapeHtml(item.module)}</span>
                  <strong>${escapeHtml(item.signal)}</strong>
                </div>
                ${renderAudienceTakeaway(item)}
                <small>${renderSourceIds(item.source_ids || [])}</small>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderAudienceTakeaway(item) {
  const rows = [
    ["盘厂客户经理看点", item.manager_focus],
    ["销售看点", item.sales_focus],
    ["战略部门看点", item.strategy_focus],
  ].filter(([, value]) => value);
  if (!rows.length) {
    return `<p>${escapeHtml(item.takeaway || "")}</p>`;
  }
  return `
    <div class="audience-takeaway-list">
      ${rows
        .map(
          ([label, value]) => `
            <div class="audience-takeaway-row">
              <b>${escapeHtml(label)}</b>
              <span>${escapeHtml(value)}</span>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderExecutiveActions(items, summary = {}) {
  if (!items.length) return "";
  return `
    <section class="executive-section">
      <div class="section-row">
        <div>
          <p class="eyebrow">Next Moves</p>
          <h3>${escapeHtml(summary.actions_heading || "施耐德行动建议")}</h3>
        </div>
        <span>${items.length} 项动作</span>
      </div>
      <div class="executive-action-table">
        ${items
          .map(
            (item) => `
              <article class="executive-action-row">
                <b>${escapeHtml(item.priority)}</b>
                <div>
                  <strong>${escapeHtml(item.action)}</strong>
                  <span>${escapeHtml(item.detail)}</span>
                  <small>${renderSourceIds(item.source_ids || [])}</small>
                </div>
                <em>${escapeHtml(item.owner)}</em>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderExecutiveWatchlist(items) {
  if (!items.length) return "";
  return `
    <section class="executive-section watchlist-section">
      <div class="section-row">
        <div>
          <p class="eyebrow">Watchlist</p>
          <h3>后续监测信号</h3>
        </div>
      </div>
      <ul>
        ${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </section>
  `;
}

function renderDashboard(project) {
  const dashboard = project.insight_dashboard;
  if (!dashboard) {
    dashboardBoard.textContent = "暂无看板数据。";
    return;
  }
  dashboardBoard.classList.remove("empty-state");
  const profile = dashboard.profile || {};
  const portrait = dashboard.portrait || {};
  const modules = normalizedModuleSummary(dashboard);
  const selectedIndex = Math.max(0, Math.min(state.selectedModuleIndex, modules.length - 1));
  state.selectedModuleIndex = selectedIndex;
  dashboardBoard.innerHTML = `
    ${renderModuleOverview(dashboard, selectedIndex)}
    ${renderProjectTaggingPanel(dashboard.project_tagging || {})}
    ${renderSelectedModulePanel(dashboard, portrait, selectedIndex)}
  `;
}

function renderSupplementPlan(project) {
  if (!supplementBoard) return;
  const plan = project.insight_dashboard?.supplement_plan || {};
  const counts = plan.counts || {};
  const items = plan.items || [];
  const moduleSummary = plan.module_summary || [];
  const gapCount = Number(counts["需补充"] || 0);
  const partialCount = Number(counts["部分完整"] || 0);
  const completeCount = Number(counts["较完整"] || 0);
  if (supplementCount) {
    supplementCount.textContent = `${gapCount} 待补 · ${partialCount} 待核验`;
  }
  supplementBoard.classList.remove("empty-state");
  supplementBoard.innerHTML = `
    <section class="supplement-summary-grid">
      ${renderSupplementKpi("需补充", gapCount, "缺少关键证据或只能内部获取", "rose")}
      ${renderSupplementKpi("部分完整", partialCount, "已有线索但需核验口径", "amber")}
      ${renderSupplementKpi("较完整", completeCount, "可直接用于当前画像", "green")}
    </section>
    <section class="supplement-module-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">9-Module Completion</p>
          <h3>按模块补数概览</h3>
        </div>
        <span>${items.length} 条补充任务</span>
      </div>
      <div class="supplement-module-grid">
        ${moduleSummary.map(renderSupplementModuleCard).join("")}
      </div>
    </section>
    <section class="supplement-task-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">Supplement Tasks</p>
          <h3>信息补充明细</h3>
        </div>
        <span>优先处理 P1</span>
      </div>
      ${renderSupplementTaskGroups(items)}
    </section>
  `;
}

function renderSupplementKpi(label, value, note, tone) {
  return `
    <article class="supplement-kpi ${tone}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(note)}</small>
    </article>
  `;
}

function renderSupplementModuleCard(item) {
  const fieldCount = Number(item.field_count || 0);
  const complete = Number(item.complete_count || 0);
  const partial = Number(item.partial_count || 0);
  const gap = Number(item.gap_count || 0);
  const pct = fieldCount ? Math.round((complete / fieldCount) * 100) : 0;
  return `
    <article class="supplement-module-card">
      <div>
        <strong>${escapeHtml(item.name)}</strong>
        <span>${fieldCount} 字段</span>
      </div>
      <div class="supplement-progress">
        <span style="width: ${Math.max(0, Math.min(100, pct))}%"></span>
      </div>
      <small>完整 ${complete} · 待核验 ${partial} · 待补 ${gap}</small>
    </article>
  `;
}

function renderSupplementTaskGroups(items) {
  if (!items.length) return `<div class="empty-state">当前企业暂无补充任务。</div>`;
  const grouped = groupItemsBy(items, (item) => item.module_name || item.module || "其他");
  return `
    <div class="supplement-task-groups">
      ${Object.entries(grouped)
        .map(([moduleName, moduleItems]) => renderSupplementTaskGroup(moduleName, moduleItems))
        .join("")}
    </div>
  `;
}

function renderSupplementTaskGroup(moduleName, items) {
  return `
    <details class="supplement-task-group" open>
      <summary>
        <span>${escapeHtml(moduleName)}</span>
        <em>${items.length} 项</em>
      </summary>
      <div class="supplement-task-table">
        ${items.map(renderSupplementTaskRow).join("")}
      </div>
    </details>
  `;
}

function renderSupplementTaskRow(item) {
  return `
    <article class="supplement-task-row">
      <div class="supplement-task-title">
        <span class="priority">${escapeHtml(item.priority || "P")}</span>
        <div>
          <strong>${escapeHtml(item.field)}</strong>
          <small>${escapeHtml(item.category || "")} · ${escapeHtml(item.description || "")}</small>
        </div>
      </div>
      <div>
        ${renderSupplementStatus(item.status)}
        <p>${escapeHtml(item.action || "")}</p>
      </div>
      <div>
        <strong>${escapeHtml(item.owner || "")}</strong>
        <small>${escapeHtml(item.data_source || "")}</small>
      </div>
      <div>
        <span>${escapeHtml(item.current_value || "暂无可用公开证据")}${renderSourceIds(item.source_ids || [])}</span>
      </div>
    </article>
  `;
}

function renderSupplementStatus(status) {
  const className = status === "需补充" ? "gap" : status === "部分完整" ? "partial" : "done";
  return `<span class="supplement-status ${className}">${escapeHtml(status || "待判断")}</span>`;
}

function groupItemsBy(items, getKey) {
  return items.reduce((groups, item) => {
    const key = getKey(item);
    groups[key] = groups[key] || [];
    groups[key].push(item);
    return groups;
  }, {});
}

function renderCustomerDossier(project, dashboard, portrait) {
  const profile = dashboard.profile || {};
  const basicInfo = dashboard.basic_info || [];
  const certifications = dashboard.certifications || [];
  const scaleFinance = dashboard.scale_finance || {};
  return `
    <section class="account-hero-card">
      <p class="eyebrow">Vitally Enterprise Profile</p>
      <h3>${escapeHtml(profile.short_name || project.customer)}</h3>
      <span>${escapeHtml(profile.account_type || "")}</span>
      <div class="hero-tags">
        ${statusTag("机会", profile.opportunity_level || "待评估", "green")}
        ${statusTag("风险", profile.risk_level || "待评估", "amber")}
      </div>
      <p>${escapeHtml(profile.relationship || "")}</p>
    </section>
    ${renderHealthLayer(dashboard, portrait)}
    ${renderModuleMarker("01", "基础信息模块", 27, "企业基本信息、资质认证、企业规模、财务状况")}
    ${renderDossierCard("企业档案", basicInfo, ["企业名称", "企业性质", "成立时间", "注册资本", "注册地址"], "Profile")}
    ${renderDossierCard("资质与准入", certifications, ["低压成套设备生产资质", "高压成套设备资质", "ISO体系认证", "施耐德授权等级"], "Certification")}
    ${renderDossierCard("规模与财务", [...(scaleFinance.enterprise_scale || []), ...(scaleFinance.financial_status || [])], ["员工总数", "生产基地数量", "年产能", "年营业收入", "净利润", "资产负债率"], "Scale")}
  `;
}

function renderHealthLayer(dashboard, portrait) {
  const profile = dashboard.profile || {};
  const statusCounts = dashboard.status_counts || {};
  const internalCount = Number(statusCounts["需内部数据"] || 0);
  const interviewCount = Number(statusCounts["需客户访谈"] || 0);
  const gapCount = (dashboard.gaps || []).length || internalCount + interviewCount;
  const valueTone = levelTone(profile.opportunity_level);
  const healthTone = internalCount + interviewCount > 40 ? "amber" : "green";
  const riskTone = levelTone(profile.risk_level, "amber");
  return `
    <section class="health-layer-card">
      <div class="section-row">
        <div>
          <p class="eyebrow">Qualtrics / Gainsight Health</p>
          <h3>企业健康层</h3>
        </div>
      </div>
      <div class="health-grid">
        ${renderHealthMetric("企业价值", profile.opportunity_level || "待评估", profile.recommended_focus || "", valueTone)}
        ${renderHealthMetric("合作健康度", healthTone === "green" ? "可经营" : "待补强", profile.relationship || "", healthTone)}
        ${renderHealthMetric("风险", profile.risk_level || "待评估", `${(dashboard.risks || []).length} 条风险摘要`, riskTone)}
        ${renderHealthMetric("待补数据", String(gapCount), `${internalCount} 内部 · ${interviewCount} 访谈`, gapCount ? "blue" : "green")}
      </div>
      ${renderMustFillMiniList(portrait.must_fill_fields || [])}
    </section>
  `;
}

function renderHealthMetric(label, value, note, tone) {
  return `
    <div class="health-metric ${tone}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(note || "")}</small>
    </div>
  `;
}

function renderMustFillMiniList(items) {
  if (!items.length) return "";
  return `
    <div class="must-fill-mini">
      ${items.slice(0, 4).map((item) => `<span>${escapeHtml(item.module)} · ${escapeHtml(item.field)}</span>`).join("")}
    </div>
  `;
}

function renderDossierCard(title, rows, preferredFields, eyebrow) {
  const selected = pickRows(rows, preferredFields).slice(0, 6);
  if (!selected.length) return "";
  return `
    <section class="dossier-card">
      <p class="eyebrow">${escapeHtml(eyebrow)}</p>
      <h3>${escapeHtml(title)}</h3>
      <div class="dossier-list">
        ${selected.map(renderDossierRow).join("")}
      </div>
    </section>
  `;
}

function renderDossierRow(row) {
  return `
    <div>
      <span>${escapeHtml(row.field)}</span>
      <strong>${escapeHtml(row.value)}${renderSourceIds(row.source_ids || [])}</strong>
    </div>
  `;
}

function renderInsightCardStack(dashboard, portrait) {
  const supplySections = dashboard.supply_procurement || [];
  const supplyRowCount = countSectionRows(supplySections);
  const supplyCategories = supplySections.map((section) => section.category).filter(Boolean).join("、");
  return `
    <section class="insight-stack">
      <div class="section-row">
        <div>
          <p class="eyebrow">Insight Cards</p>
          <h3>核心洞察卡片</h3>
        </div>
        <span>复用已检索数据</span>
      </div>
      ${renderSummaryInsightCard(dashboard, portrait)}
      ${renderInsightDetails("02 业务能力模块", "19 字段 · 能力、产品线、项目经验", renderBusinessCapability(dashboard.business_capability || []), true)}
      ${renderInsightDetails("03 供应链与采购模块", `${supplyRowCount} 字段 · ${supplyCategories || "供应链与采购"}`, renderSupplyProcurement(supplySections), true)}
      ${renderInsightDetails("04 客户资源模块", "8 字段 · 客户结构、客户关系", renderCustomerResources(dashboard.customer_resources || []))}
      ${renderInsightDetails("05 销售与市场模块", "11 字段 · 销售体系、市场覆盖、价格策略", renderSalesMarket(dashboard.sales_market || []))}
      ${renderInsightDetails("06 组织架构与决策链模块", "12 字段 · 关键人、部门和流程", renderOrgDecision(dashboard.org_decision || [], dashboard.org_decision_blueprint || {}))}
      ${renderInsightDetails("07 发展战略与需求模块", "13 字段 · 发展、数字化、绿色低碳、电气升级", renderStrategyNeeds(dashboard.strategy_needs || []))}
      ${renderInsightDetails("08 痛点与机会模块", "10 字段 · 业务、技术、市场痛点转行动机会", renderPainOpportunities(dashboard.pain_opportunities || []))}
    </section>
  `;
}

function countSectionRows(sections) {
  return (sections || []).reduce((total, section) => total + (section.rows || []).length, 0);
}

function renderSummaryInsightCard(dashboard, portrait) {
  return `
    <article class="summary-insight-card">
      <div>
        <p class="eyebrow">Executive Brief</p>
        <h3>${escapeHtml(portrait.headline || "企业洞察摘要")}</h3>
        <p>${escapeHtml(dashboard.summary || portrait.business_role || "")}</p>
      </div>
      <div class="summary-chip-grid">
        ${(portrait.tags || []).slice(0, 5).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
      </div>
    </article>
  `;
}

function renderInsightDetails(title, subtitle, content, open = false) {
  if (!content) return "";
  return `
    <details class="insight-details"${open ? " open" : ""}>
      <summary>
        <span>${escapeHtml(title)}</span>
        <em>${escapeHtml(subtitle)}</em>
      </summary>
      <div class="insight-detail-body">${content}</div>
    </details>
  `;
}

function renderActionRiskRail(dashboard, portrait) {
  return `
    ${renderNextBestActions(dashboard.actions || [], dashboard.opportunities || [])}
    ${renderRiskRail(dashboard, portrait)}
    ${renderDataGapRail(dashboard.gaps || [], portrait.must_fill_fields || [])}
    ${renderCoverageRail(dashboard)}
  `;
}

function renderNextBestActions(actions, opportunities) {
  const primaryActions = actions.length ? actions : opportunities.slice(0, 5);
  return `
    <section class="rail-card next-actions-card">
      <div class="section-row">
        <div>
          <p class="eyebrow">Next Best Action</p>
          <h3>推荐动作</h3>
        </div>
        <span>${primaryActions.length} 项</span>
      </div>
      ${renderRailActionList(primaryActions)}
    </section>
  `;
}

function renderRailActionList(items) {
  if (!items.length) return `<div class="empty-state">暂无行动建议。</div>`;
  return `
    <div class="rail-action-list">
      ${items
        .slice(0, 5)
        .map((item) => {
          const stage = item["周期"] || item["优先级"] || "P";
          const title = item["目标"] || item["机会主题"] || "";
          const action = item["动作"] || item["下一步动作"] || item["推荐方案"] || item["推荐切入方案"] || "";
          return `
            <article>
              <span class="priority">${escapeHtml(stage)}</span>
              <div>
                <strong>${escapeHtml(title)}</strong>
                <p>${escapeHtml(action)}</p>
              </div>
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderRiskRail(dashboard, portrait) {
  return `
    <section class="rail-card">
      <div class="section-row">
        <div>
          <p class="eyebrow">Risk</p>
          <h3>09 风险评估模块</h3>
        </div>
        ${statusTag("6 字段", dashboard.profile?.risk_level || "待评估", "amber")}
      </div>
      ${renderRiskList(dashboard.risks || portrait.top_risks || [])}
      ${renderRiskAssessment(dashboard.risk_assessment || [])}
    </section>
  `;
}

function renderDataGapRail(gaps, mustFillFields) {
  const items = mustFillFields.length ? mustFillFields : gaps.slice(0, 5);
  return `
    <section class="rail-card">
      <div class="section-row">
        <div>
          <p class="eyebrow">Data Gaps</p>
          <h3>待补数据</h3>
        </div>
        <span>${gaps.length || items.length} 项</span>
      </div>
      <div class="rail-gap-list">
        ${
          items.length
            ? items
                .slice(0, 6)
                .map((item) => `<div><strong>${escapeHtml(item.field)}</strong><span>${escapeHtml(item.module || item.module_name || "")} · ${escapeHtml(item.status || "")}</span></div>`)
                .join("")
            : `<div class="empty-state">暂无待补数据。</div>`
        }
      </div>
    </section>
  `;
}

function renderCoverageRail(dashboard) {
  return `
    <section class="rail-card compact-coverage-card">
      <div class="section-row">
        <div>
          <p class="eyebrow">Framework Coverage</p>
          <h3>大纲覆盖</h3>
        </div>
      </div>
      ${(dashboard.module_summary || []).map(renderModuleCoverage).join("")}
    </section>
  `;
}

function renderModuleOverview(dashboard, selectedIndex) {
  const modules = normalizedModuleSummary(dashboard);
  return `
    <section class="module-overview">
      <div class="section-row">
        <div>
          <p class="eyebrow">9-Module Insight Map</p>
          <h3>企业洞察 9 模块地图</h3>
        </div>
        <span>${modules.reduce((total, item) => total + Number(item.field_count || 0), 0)} 字段</span>
      </div>
      <div class="module-overview-grid">
        ${modules.map((item, index) => renderModuleOverviewCard(item, index, selectedIndex)).join("")}
      </div>
    </section>
  `;
}

function renderModuleOverviewCard(item, index, selectedIndex) {
  const name = cleanModuleName(item.name);
  return `
    <button class="module-overview-card ${modulePlacementClass(name)}${index === selectedIndex ? " is-selected" : ""}" data-module-index="${index}" type="button" aria-pressed="${index === selectedIndex}">
      <span>${String(index + 1).padStart(2, "0")}</span>
      <div>
        <strong>${escapeHtml(name)}</strong>
        <small>${Number(item.field_count || 0)} 字段 · ${escapeHtml(modulePlacementLabel(name))}</small>
      </div>
    </button>
  `;
}

function renderSourceCoverage(project) {
  const sources = Object.values(project.source_references || {});
  if (!sources.length) return "";
  const grouped = groupSourcesByType(sources);
  return `
    <section class="source-coverage-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">Source Coverage</p>
          <h3>数据来源目录</h3>
        </div>
        <span>${sources.length} 个来源 · 9 大模块引用</span>
      </div>
      <div class="source-type-grid">
        ${Object.entries(grouped).map(([type, items]) => renderSourceTypeCard(type, items)).join("")}
      </div>
    </section>
  `;
}

function renderSourceTypeCard(type, items) {
  return `
    <article class="source-type-card">
      <div>
        <strong>${escapeHtml(type)}</strong>
        <span>${items.length} 个来源</span>
      </div>
      <ul>
        ${items
          .slice(0, 3)
          .map((item) => {
            const label = `${item.id} · ${item.title}`;
            const content = isExternalUrl(item.url)
              ? `<a href="${escapeAttr(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`
              : `<span>${escapeHtml(label)}</span>`;
            return `<li>${content}</li>`;
          })
          .join("")}
      </ul>
    </article>
  `;
}

function renderReferenceSources(project) {
  if (!sourceBoard) return;
  const coverage = buildReferenceSourceCoverage(project);
  const clickableCount = coverage.sources.filter((item) => isExternalUrl(item.source?.url || "")).length;
  if (sourceCount) {
    sourceCount.textContent = `${coverage.sources.length} 来源 · ${clickableCount} 可点击`;
  }
  if (!coverage.sources.length) {
    sourceBoard.classList.add("empty-state");
    sourceBoard.textContent = "暂无参考数据源。";
    return;
  }
  sourceBoard.classList.remove("empty-state");
  sourceBoard.innerHTML = `
    <section class="reference-source-table-panel reference-source-simple">
      <div class="section-row">
        <div>
          <p class="eyebrow">Source Register</p>
          <h3>数据来源目录</h3>
        </div>
        <span>${coverage.sources.length} 个来源 · ${clickableCount} 个外部链接</span>
      </div>
      <div class="reference-source-table">
        <div class="reference-source-row is-head">
          <strong>编号</strong>
          <span>数据来源</span>
          <span>发布方/日期</span>
          <span>链接</span>
        </div>
        ${coverage.sources.map(renderReferenceSourceRow).join("")}
      </div>
    </section>
  `;
}

function renderReferenceKpi(label, value, note) {
  return `
    <article class="reference-kpi-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(note)}</small>
    </article>
  `;
}

function renderReferenceModuleCard(item) {
  const sourceIds = item.source_ids || [];
  return `
    <article class="reference-module-card">
      <div>
        <strong>${escapeHtml(item.module)}</strong>
        <span>${sourceIds.length} 个来源 · ${Number(item.usage_count || 0)} 条引用</span>
      </div>
      <p>${sourceIds.length ? renderSourceIds(sourceIds) : "暂无直接引用来源"}</p>
    </article>
  `;
}

function renderReferenceSourceRow(item) {
  const source = item.source || {};
  const sourceId = source.id || "";
  const title = source.title || "未命名来源";
  return `
    <div class="reference-source-row">
      <strong>
        ${escapeHtml(sourceId)}
        <small>${escapeHtml(item.type || "未分类")}</small>
      </strong>
      <span>
        ${escapeHtml(title)}
        <small>${escapeHtml(source.purpose || "用于支撑企业洞察判断")}</small>
      </span>
      <span>
        ${escapeHtml(source.publisher || "待补")}
        <small>${escapeHtml(source.date || "")}</small>
      </span>
      <span>${sourceOpenLink(source)}</span>
    </div>
  `;
}

function sourceLink(source, label) {
  if (source && isExternalUrl(source.url || "")) {
    return `<a href="${escapeAttr(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
  }
  return escapeHtml(label);
}

function sourceOpenLink(source) {
  if (source && isExternalUrl(source.url || "")) {
    return `<a class="reference-link-button" href="${escapeAttr(source.url)}" target="_blank" rel="noreferrer">打开来源</a>`;
  }
  const url = String(source?.url || "");
  if (url) {
    return `<em class="reference-link-note" title="${escapeAttr(url)}">本地/内部资料</em>`;
  }
  return `<em class="reference-link-note">待补链接</em>`;
}

function buildReferenceSourceCoverage(project) {
  const dashboard = project.insight_dashboard || {};
  const sourceReferences = project.source_references || {};
  const usageBySource = {};
  const addUsage = (sourceIds, module, field, detail = "") => {
    (sourceIds || []).forEach((sourceId) => {
      if (!sourceId) return;
      const key = String(sourceId);
      if (!usageBySource[key]) usageBySource[key] = [];
      const usageKey = `${module}|${field}|${detail}`;
      if (!usageBySource[key].some((item) => item.key === usageKey)) {
        usageBySource[key].push({ key: usageKey, module, field, detail });
      }
    });
  };

  const addSectionRows = (sections, moduleLabel) => {
    (sections || []).forEach((section) => {
      (section.rows || []).forEach((row) => {
        addUsage(row.source_ids, moduleLabel, `${section.category || "字段"} / ${row.field || ""}`, shortSourceDetail(row.value || row.pain || row.description || ""));
      });
    });
  };

  const summary = dashboard.competitor_summary || {};
  (summary.key_analysis || []).forEach((item) => {
    const detail = [item.analysis, item.what_to_do, item.risk_or_watch].filter(Boolean).join(" ");
    addUsage(item.source_ids, "摘要", `${item.audience || ""} / ${item.title || "关键分析"}`, shortSourceDetail(detail));
  });
  (summary.substitution_chain || []).forEach((item) => addUsage(item.source_ids, "摘要", item.stage || "经营链路", shortSourceDetail(item.insight || "")));
  (summary.module_takeaways || []).forEach((item) => {
    const detail = [item.manager_focus, item.sales_focus, item.strategy_focus, item.takeaway].filter(Boolean).join(" ");
    addUsage(item.source_ids, item.module || "摘要", item.signal || "模块结论", shortSourceDetail(detail));
  });
  (summary.actions || []).forEach((item) => addUsage(item.source_ids, "摘要", item.action || "推进动作", shortSourceDetail(item.detail || "")));

  addSectionRows(dashboard.business_capability, "02 业务能力模块");
  addSectionRows(dashboard.supply_procurement, "03 供应链与采购模块");
  addSectionRows(dashboard.customer_resources, "04 客户资源模块");
  addSectionRows(dashboard.sales_market, "05 销售与市场模块");
  addSectionRows(dashboard.org_decision, "06 组织架构与决策链模块");
  addSectionRows(dashboard.strategy_needs, "07 发展战略与需求模块");
  addSectionRows(dashboard.pain_opportunities, "08 痛点与机会模块");
  addSectionRows(dashboard.risk_assessment, "09 风险评估模块");

  const blueprint = dashboard.org_decision_blueprint || {};
  (blueprint.path || []).forEach((item) => addUsage(item.source_ids, "06 组织架构与决策链模块", item.stage || "决策路径", shortSourceDetail(item.signal || "")));
  (blueprint.contacts || []).forEach((item) => addUsage(item.source_ids, "06 组织架构与决策链模块", item.role || "优先触点", shortSourceDetail(item.evidence || "")));
  const tagging = dashboard.project_tagging || {};
  addUsage(tagging.source_ids, "项目打标与调研重点", "方法来源", shortSourceDetail(tagging.headline || ""));
  const supplement = dashboard.supplement_plan || {};
  (supplement.items || []).forEach((item) => addUsage(item.source_ids, item.module || "信息补充", `${item.category || ""} / ${item.field || ""}`, shortSourceDetail(item.current_value || "")));

  const knownSourceIds = new Set([...Object.keys(sourceReferences), ...Object.keys(usageBySource)]);
  const sources = Array.from(knownSourceIds)
    .sort((a, b) => sourceSortKey(a).localeCompare(sourceSortKey(b), "zh-Hans-CN"))
    .map((sourceId) => {
      const source = sourceReferences[sourceId] || { id: sourceId, title: "未登记来源", publisher: "", date: "", url: "", purpose: "洞察模块引用但来源登记待补齐" };
      const usage = (usageBySource[sourceId] || []).map(({ key, ...item }) => item);
      return {
        source,
        usage,
        type: inferSourceType(source),
        module_ids: Array.from(new Set(usage.map((item) => item.module))).filter(Boolean),
      };
    });
  const groupedRaw = {};
  sources.forEach((item) => {
    if (!groupedRaw[item.type]) groupedRaw[item.type] = [];
    groupedRaw[item.type].push(item.source);
  });
  const grouped = orderSourceGroups(groupedRaw);
  const moduleCoverage = buildSourceModuleCoverage(usageBySource);
  return {
    sources,
    grouped,
    moduleCoverage,
    usedModuleCount: moduleCoverage.filter((item) => item.source_ids.length).length,
    usageCount: Object.values(usageBySource).reduce((total, items) => total + items.length, 0),
  };
}

function buildSourceModuleCoverage(usageBySource) {
  const modules = [
    "01 基础信息模块",
    "02 业务能力模块",
    "03 供应链与采购模块",
    "04 客户资源模块",
    "05 销售与市场模块",
    "06 组织架构与决策链模块",
    "07 发展战略与需求模块",
    "08 痛点与机会模块",
    "09 风险评估模块",
  ];
  return modules.map((module) => {
    const sourceIds = [];
    let usageCount = 0;
    Object.entries(usageBySource).forEach(([sourceId, items]) => {
      const hits = items.filter((item) => normalizeModuleNameForSource(item.module) === module);
      if (hits.length) {
        sourceIds.push(sourceId);
        usageCount += hits.length;
      }
    });
    return { module, source_ids: sourceIds.sort(sourceIdCompare), usage_count: usageCount };
  });
}

function normalizeModuleNameForSource(module) {
  const text = String(module || "");
  const match = text.match(/0?[1-9]\s*[\.\s]\s*([^/]+)/);
  if (match) {
    const number = text.match(/0?([1-9])/)[1].padStart(2, "0");
    return `${number} ${match[1].replace(/^模块/, "").trim()}`;
  }
  if (text.includes("基础信息")) return "01 基础信息模块";
  if (text.includes("业务能力")) return "02 业务能力模块";
  if (text.includes("供应链")) return "03 供应链与采购模块";
  if (text.includes("客户资源")) return "04 客户资源模块";
  if (text.includes("销售与市场")) return "05 销售与市场模块";
  if (text.includes("组织架构")) return "06 组织架构与决策链模块";
  if (text.includes("发展战略")) return "07 发展战略与需求模块";
  if (text.includes("痛点与机会")) return "08 痛点与机会模块";
  if (text.includes("风险评估")) return "09 风险评估模块";
  return text;
}

function orderSourceGroups(groups) {
  const order = ["企业官网/官方IR", "官方微信/官方媒体", "政府/公共资源", "证券公告/券商研究", "行业权威/项目平台", "招聘/人才平台", "用户附件/内部材料"];
  return Object.fromEntries(order.filter((type) => groups[type]?.length).map((type) => [type, groups[type]]));
}

function sourceSortKey(sourceId) {
  const match = String(sourceId).match(/^([A-Za-z]+)(\d+)$/);
  if (!match) return String(sourceId);
  return `${match[1]}${String(Number(match[2])).padStart(4, "0")}`;
}

function sourceIdCompare(a, b) {
  return sourceSortKey(a).localeCompare(sourceSortKey(b), "zh-Hans-CN");
}

function shortSourceDetail(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > 52 ? `${text.slice(0, 52)}...` : text;
}

function renderProjectTaggingPanel(tagging) {
  const groups = tagging.tag_groups || [];
  if (!groups.length) return "";
  const researchFocus = tagging.research_focus || [];
  const solutionMap = tagging.solution_map || [];
  const nextOutputs = tagging.next_outputs || [];
  return `
    <section class="project-tagging-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">Project Tagging</p>
          <h3>油气化工项目打标与调研重点</h3>
        </div>
        <span>${groups.length} 组标签 · ${solutionMap.length} 层清单</span>
      </div>
      <div class="tagging-headline">
        <strong>${escapeHtml(tagging.headline || "按角色、阶段、层级和证据打标")}</strong>
        <p>把KA从“集团企业画像”落到“基地-装置-项目包-角色-证据”的可执行标签，用于项目打标、企业洞察和下一步访谈。</p>
        <small>方法来源${renderSourceIds(tagging.source_ids || [])}</small>
      </div>
      <div class="tagging-grid">
        ${groups.map(renderTaggingCard).join("")}
      </div>
      <div class="research-solution-grid">
        <article class="research-focus-panel">
          <div>
            <p class="eyebrow">Research Focus</p>
            <h3>拜访前必查问题</h3>
          </div>
          <div class="research-focus-list">
            ${researchFocus.map(renderResearchFocus).join("")}
          </div>
        </article>
        <article class="solution-map-panel">
          <div>
            <p class="eyebrow">3 Layers + 2 Loops</p>
            <h3>三层两闭环证据链</h3>
          </div>
          <div class="solution-map-list">
            ${solutionMap.map(renderSolutionMapItem).join("")}
          </div>
          ${
            nextOutputs.length
              ? `<div class="next-output-strip">${nextOutputs.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`
              : ""
          }
        </article>
      </div>
    </section>
  `;
}

function renderTaggingCard(group) {
  const tags = group.tags || [];
  return `
    <article class="tagging-card">
      <h3>${escapeHtml(group.name || "")}</h3>
      <div class="tag-pill-list">
        ${tags.map((tag) => `<span class="tag-pill">${escapeHtml(tag)}</span>`).join("")}
      </div>
      <p>${escapeHtml(group.why || "")}</p>
    </article>
  `;
}

function renderResearchFocus(item) {
  const questions = item.questions || [];
  return `
    <details class="research-focus-item" open>
      <summary>${escapeHtml(item.topic || "调研重点")}</summary>
      <ul>
        ${questions.map((question) => `<li>${escapeHtml(question)}</li>`).join("")}
      </ul>
    </details>
  `;
}

function renderSolutionMapItem(item) {
  return `
    <div class="solution-map-item">
      <strong>${escapeHtml(item.layer || "")}</strong>
      <span>${escapeHtml(item.focus || "")}</span>
      <em>${escapeHtml(item.evidence || "")}</em>
    </div>
  `;
}

function groupSourcesByType(sources) {
  const order = ["企业官网/官方IR", "官方微信/官方媒体", "政府/公共资源", "证券公告/券商研究", "行业权威/项目平台", "招聘/人才平台", "用户附件/内部材料"];
  const groups = Object.fromEntries(order.map((type) => [type, []]));
  sources.forEach((source) => {
    const type = inferSourceType(source);
    groups[type].push(source);
  });
  return Object.fromEntries(order.filter((type) => groups[type].length).map((type) => [type, groups[type]]));
}

function inferSourceType(source) {
  const text = `${source.title || ""} ${source.publisher || ""} ${source.url || ""} ${source.purpose || ""}`;
  if (/AI洞察|用户提供|Downloads/.test(text)) return "用户附件/内部材料";
  if (/微信|公众号|官方媒体|国资报告|集团报道/.test(text)) return "官方微信/官方媒体";
  if (/chint\.net|chint\.com|xjgc\.com|cee-group|sinopec|cnpc|petrochina|cnooc|shell\.com|basf\.com|exxonmobil|whchem|cnrspc|se\.com|schneider-electric|官网|投资者关系|联系我们|集团官网|Annual Report/.test(text)) return "企业官网/官方IR";
  if (/gov\.cn|sasac|ggzy|公共资源|水利局|科技厅|政府|高新技术企业|公示|国资委|cx\.cnca\.cn|zzxy\.nea\.gov\.cn|国家能源局|认证认可信息公共服务平台/.test(text)) return "政府/公共资源";
  if (/sse|szse|cninfo|新浪财经|东方财富|证券|券商|研报|公告|股票|finance|10jqka|cfi\.net|中财网/.test(text)) return "证券公告/券商研究";
  if (/news\.cn|新华社|中国经济网|ISO|iso\.org|cqc\.com\.cn|中国质量认证中心|中车|电建|核电|行业|协会|招投标|中标|候选|采购|项目/.test(text)) return "行业权威/项目平台";
  if (/招聘|人才|zhaopin|yzrc|智联/.test(text)) return "招聘/人才平台";
  return "行业权威/项目平台";
}

function renderSelectedModulePanel(dashboard, portrait, selectedIndex) {
  const modules = normalizedModuleSummary(dashboard);
  const module = modules[selectedIndex] || modules[0] || {};
  const number = String(selectedIndex + 1).padStart(2, "0");
  const name = cleanModuleName(module.name);
  return `
    <section class="selected-module-panel" id="selectedModulePanel">
      <div class="selected-module-header">
        <span>${escapeHtml(number)}</span>
        <div>
          <p class="eyebrow">Selected Module</p>
          <h3>${escapeHtml(name || "模块详情")}</h3>
        </div>
        <strong>${Number(module.field_count || 0)} 字段</strong>
      </div>
      <div class="selected-module-content">
        ${renderSelectedModuleContent(selectedIndex, dashboard, portrait)}
      </div>
    </section>
  `;
}

function renderSelectedModuleContent(selectedIndex, dashboard, portrait) {
  const scaleFinance = dashboard.scale_finance || {};
  const renderers = [
    () => [renderBasicInfo(dashboard.basic_info || []), renderCertifications(dashboard.certifications || []), renderScaleFinance(scaleFinance)].join(""),
    () => renderBusinessCapability(dashboard.business_capability || []),
    () => renderSupplyProcurement(dashboard.supply_procurement || []),
    () => renderCustomerResources(dashboard.customer_resources || []),
    () => renderSalesMarket(dashboard.sales_market || []),
    () => renderOrgDecision(dashboard.org_decision || [], dashboard.org_decision_blueprint || {}),
    () => renderStrategyNeeds(dashboard.strategy_needs || []),
    () => renderPainOpportunities(dashboard.pain_opportunities || []),
    () => renderRiskAssessment(dashboard.risk_assessment || []),
  ];
  const content = renderers[selectedIndex]?.() || "";
  if (content) return content;
  const gaps = portrait.must_fill_fields || dashboard.gaps || [];
  return gaps.length
    ? `<div class="empty-state">该模块仍需补充数据，可先查看右侧待补数据清单。</div>`
    : `<div class="empty-state">暂无该模块明细。</div>`;
}

function renderModuleMarker(number, title, fieldCount, note) {
  return `
    <section class="module-marker">
      <span>${escapeHtml(number)}</span>
      <div>
        <p class="eyebrow">${fieldCount} 字段</p>
        <h3>${escapeHtml(title)}</h3>
        <small>${escapeHtml(note)}</small>
      </div>
    </section>
  `;
}

function normalizedModuleSummary(dashboard) {
  const summary = dashboard.module_summary?.length ? dashboard.module_summary : state.framework;
  return (summary || []).map((item) => ({
    name: item.name || item.module || "",
    field_count: item.field_count || 0,
  }));
}

function modulePlacementLabel(name) {
  if (name === "基础信息模块") return "左侧企业档案";
  if (name === "风险评估模块") return "右侧风险栏";
  return "中间洞察卡片";
}

function modulePlacementClass(name) {
  if (name === "基础信息模块") return "left";
  if (name === "风险评估模块") return "right";
  return "center";
}

function pickRows(rows, preferredFields) {
  const byField = new Map((rows || []).map((row) => [row.field, row]));
  const selected = preferredFields.map((field) => byField.get(field)).filter(Boolean);
  if (selected.length >= preferredFields.length) return selected;
  const used = new Set(selected.map((row) => row.field));
  return selected.concat((rows || []).filter((row) => !used.has(row.field))).slice(0, preferredFields.length);
}

function levelTone(value, fallback = "blue") {
  const text = String(value || "");
  if (text.includes("高")) return "green";
  if (text.includes("中")) return "amber";
  if (text.includes("低")) return "rose";
  return fallback;
}

function renderBasicInfo(items) {
  if (!items.length) return "";
  return `
    <section class="basic-info-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">基础信息</p>
          <h3>企业基本信息</h3>
        </div>
        <span>9 个字段 · 对齐 Excel 大纲</span>
      </div>
      <div class="basic-info-table">
        ${items.map(renderBasicInfoRow).join("")}
      </div>
    </section>
  `;
}

function renderCertifications(items) {
  if (!items.length) return "";
  return `
    <section class="certification-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">资质认证</p>
          <h3>资质认证</h3>
        </div>
        <span>7 个字段 · 对齐 Excel 大纲</span>
      </div>
      <div class="certification-table">
        ${items.map(renderCertificationRow).join("")}
      </div>
    </section>
  `;
}

function renderCertificationRow(item) {
  return `
    <div class="certification-row">
      <strong>${escapeHtml(item.field)}</strong>
      <span>${escapeHtml(item.value)}</span>
      <em>${escapeHtml(item.description || "")}${renderSourceIds(item.source_ids || [])}</em>
    </div>
  `;
}

function renderScaleFinance(data) {
  const enterpriseScale = data.enterprise_scale || [];
  const financialStatus = data.financial_status || [];
  if (!enterpriseScale.length && !financialStatus.length) return "";
  return `
    <section class="scale-finance-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">企业规模与财务状况</p>
          <h3>企业规模 / 财务状况</h3>
        </div>
        <span>${enterpriseScale.length + financialStatus.length} 个字段 · 对齐 Excel 大纲</span>
      </div>
      <div class="scale-finance-grid">
        ${renderMetricTable("企业规模", enterpriseScale)}
        ${renderMetricTable("财务状况", financialStatus)}
      </div>
    </section>
  `;
}

function renderMetricTable(title, items) {
  return `
    <div class="metric-table-wrap">
      <h3>${escapeHtml(title)}</h3>
      <div class="metric-table">
        ${items.map(renderMetricRow).join("")}
      </div>
    </div>
  `;
}

function renderMetricRow(item) {
  return `
    <div class="metric-row">
      <strong>${escapeHtml(item.field)}</strong>
      <span>${escapeHtml(item.value)}</span>
      <em>${escapeHtml(item.description || "")}${renderSourceIds(item.source_ids || [])}</em>
    </div>
  `;
}

function renderBusinessCapability(sections) {
  if (!sections.length) return "";
  const rowCount = sections.reduce((total, section) => total + (section.rows || []).length, 0);
  return `
    <section class="business-capability-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">业务能力模块</p>
          <h3>业务能力全景</h3>
        </div>
        <span>${rowCount} 个字段 · 对齐 Excel 大纲</span>
      </div>
      <div class="business-capability-grid">
        ${sections.map(renderBusinessCategory).join("")}
      </div>
    </section>
  `;
}

function renderBusinessCategory(section) {
  const rows = section.rows || [];
  return `
    <article class="business-category">
      <h3>${escapeHtml(section.category || "")}</h3>
      <div class="business-table">
        ${rows.map(renderBusinessRow).join("")}
      </div>
    </article>
  `;
}

function renderBusinessRow(item) {
  return `
    <div class="business-row">
      <strong>${escapeHtml(item.field)}</strong>
      <span>${escapeHtml(item.value)}</span>
      <em>${escapeHtml(item.description || "")}${renderSourceIds(item.source_ids || [])}</em>
    </div>
  `;
}

function renderSupplyProcurement(sections) {
  if (!sections.length) return "";
  const rowCount = sections.reduce((total, section) => total + (section.rows || []).length, 0);
  return `
    <section class="supply-procurement-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">供应链与采购模块</p>
          <h3>供应链与采购画像</h3>
        </div>
        <span>${rowCount} 个字段 · 对齐 Excel 大纲</span>
      </div>
      <div class="supply-procurement-grid">
        ${sections.map(renderSupplyProcurementCategory).join("")}
      </div>
    </section>
  `;
}

function renderSupplyProcurementCategory(section) {
  const rows = section.rows || [];
  return `
    <article class="supply-procurement-category">
      <h3>${escapeHtml(section.category || "")}</h3>
      <div class="supply-procurement-table">
        ${rows.map(renderSupplyProcurementRow).join("")}
      </div>
    </article>
  `;
}

function renderSupplyProcurementRow(item) {
  return `
    <div class="supply-procurement-row">
      <strong>${escapeHtml(item.field)}</strong>
      <span>${escapeHtml(item.value)}</span>
      <em>${escapeHtml(item.description || "")}${renderSourceIds(item.source_ids || [])}</em>
      ${renderCompetitorSolutionComparison(item.comparison_rows || [])}
      ${renderSupplierSegmentTable(item.supplier_segments || [])}
      ${renderSupplyEvidenceTable(item.evidence_rows || [], item.evidence_title || "", item.evidence_subtitle || "")}
    </div>
  `;
}

function renderCompetitorSolutionComparison(rows) {
  if (!rows.length) return "";
  return `
    <div class="competitor-solution-table-wrap">
      <div class="competitor-solution-title">
        <strong>业务需求导向竞品方案对比</strong>
        <span>以该企业实际项目需求比较施耐德与主要竞争对手</span>
      </div>
      <table class="competitor-solution-table">
        <thead>
          <tr>
            <th>业务需求</th>
            <th>采购/项目触发</th>
            <th>施耐德方案与产品</th>
            <th>竞争对手方案与产品</th>
            <th>施耐德优势</th>
            <th>施耐德劣势/需防守点</th>
            <th>引用</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td>${escapeHtml(row.business_need || "")}</td>
              <td>${escapeHtml(row.demand_trigger || "")}</td>
              <td>${escapeHtml(row.schneider_solution || "")}</td>
              <td>${escapeHtml(row.competitor_solution || "")}</td>
              <td>${escapeHtml(row.schneider_strength || "")}</td>
              <td>${escapeHtml(row.schneider_gap || "")}</td>
              <td>${renderSourceIds(row.source_ids || [])}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderSupplierSegmentTable(rows) {
  if (!rows.length) return "";
  return `
    <div class="supplier-segment-table-wrap">
      <div class="supplier-segment-title">
        <strong>非竞品供应链分层</strong>
        <span>排除施耐德主要竞品整机品牌后的其他供应商线索</span>
      </div>
      <table class="supplier-segment-table">
        <thead>
          <tr>
            <th>供应商类别</th>
            <th>公开证据</th>
            <th>业务意义</th>
            <th>施耐德经营提示</th>
            <th>引用</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td>${escapeHtml(row.segment || "")}</td>
              <td>${escapeHtml(row.public_evidence || "")}</td>
              <td>${escapeHtml(row.business_meaning || "")}</td>
              <td>${escapeHtml(row.se_implication || "")}</td>
              <td>${renderSourceIds(row.source_ids || [])}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderSupplyEvidenceTable(rows, title, subtitle) {
  if (!rows.length) return "";
  return `
    <div class="supplier-segment-table-wrap">
      <div class="supplier-segment-title">
        <strong>${escapeHtml(title || "供应链证据表")}</strong>
        <span>${escapeHtml(subtitle || "公开证据、判断与施耐德经营提示")}</span>
      </div>
      <table class="supplier-segment-table">
        <thead>
          <tr>
            <th>研究层级</th>
            <th>公开证据</th>
            <th>判断</th>
            <th>施耐德经营提示</th>
            <th>引用</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td>${escapeHtml(row.segment || "")}</td>
              <td>${escapeHtml(row.public_evidence || "")}</td>
              <td>${escapeHtml(row.judgement || "")}</td>
              <td>${escapeHtml(row.se_implication || "")}</td>
              <td>${renderSourceIds(row.source_ids || [])}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderCustomerResources(sections) {
  if (!sections.length) return "";
  const rowCount = sections.reduce((total, section) => total + (section.rows || []).length, 0);
  return `
    <section class="customer-resources-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">客户资源模块</p>
          <h3>客户资源画像</h3>
        </div>
        <span>${rowCount} 个字段 · 对齐 Excel 大纲</span>
      </div>
      <div class="customer-resources-grid">
        ${sections.map(renderCustomerResourceCategory).join("")}
      </div>
    </section>
  `;
}

function renderCustomerResourceCategory(section) {
  const rows = section.rows || [];
  return `
    <article class="customer-resource-category">
      <h3>${escapeHtml(section.category || "")}</h3>
      <div class="customer-resource-table">
        ${rows.map(renderCustomerResourceRow).join("")}
      </div>
    </article>
  `;
}

function renderCustomerResourceRow(item) {
  return `
    <div class="customer-resource-row">
      <strong>${escapeHtml(item.field)}</strong>
      <span>${escapeHtml(item.value)}</span>
      <em>${escapeHtml(item.description || "")}${renderSourceIds(item.source_ids || [])}</em>
    </div>
  `;
}

function renderSalesMarket(sections) {
  if (!sections.length) return "";
  const rowCount = sections.reduce((total, section) => total + (section.rows || []).length, 0);
  return `
    <section class="sales-market-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">销售与市场模块</p>
          <h3>销售与市场画像</h3>
        </div>
        <span>${rowCount} 个字段 · 对齐 Excel 大纲</span>
      </div>
      <div class="sales-market-grid">
        ${sections.map(renderSalesMarketCategory).join("")}
      </div>
    </section>
  `;
}

function renderSalesMarketCategory(section) {
  const rows = section.rows || [];
  return `
    <article class="sales-market-category">
      <h3>${escapeHtml(section.category || "")}</h3>
      <div class="sales-market-table">
        ${rows.map(renderSalesMarketRow).join("")}
      </div>
    </article>
  `;
}

function renderSalesMarketRow(item) {
  return `
    <div class="sales-market-row">
      <strong>${escapeHtml(item.field)}</strong>
      <span>${escapeHtml(item.value)}</span>
      <em>${escapeHtml(item.description || "")}${renderSourceIds(item.source_ids || [])}</em>
    </div>
  `;
}

function renderOrgDecision(sections, blueprint = {}) {
  if (!sections.length) return "";
  const rowCount = sections.reduce((total, section) => total + (section.rows || []).length, 0);
  const blueprintAfterDecision = shouldPlaceBlueprintAfterDecision(blueprint);
  return `
    <section class="org-decision-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">组织架构与决策链模块</p>
          <h3>组织与决策链画像</h3>
        </div>
        <span>${rowCount} 个字段 · 对齐 Excel 大纲</span>
      </div>
      ${blueprintAfterDecision ? "" : renderOrgDecisionBlueprint(blueprint)}
      <div class="org-decision-grid">
        ${renderOrgDecisionCategories(sections, blueprint, blueprintAfterDecision)}
      </div>
    </section>
  `;
}

function shouldPlaceBlueprintAfterDecision(blueprint) {
  const title = blueprint.title || "";
  return title.includes("竞品") || title.includes("竞争链路图");
}

function renderOrgDecisionCategories(sections, blueprint, insertBlueprintAfterDecision) {
  if (!insertBlueprintAfterDecision) return sections.map(renderOrgDecisionCategory).join("");
  const blueprintMarkup = renderOrgDecisionBlueprint(blueprint);
  let inserted = false;
  const html = sections
    .map((section) => {
      const category = renderOrgDecisionCategory(section);
      if (!inserted && section.category === "决策流程") {
        inserted = true;
        return `${category}${blueprintMarkup}`;
      }
      return category;
    })
    .join("");
  return inserted ? html : `${html}${blueprintMarkup}`;
}

function renderOrgDecisionBlueprint(blueprint) {
  const path = blueprint.decision_path || [];
  const contacts = blueprint.priority_contacts || [];
  const rules = blueprint.decision_rules || [];
  const missing = blueprint.missing_data || [];
  if (!path.length && !contacts.length && !rules.length && !missing.length) return "";
  return `
    <div class="org-blueprint">
      <div class="org-blueprint-header">
        <strong>${escapeHtml(blueprint.title || "决策链作战图")}</strong>
        <span>路径 · 触点 · 规则 · 待补</span>
      </div>
      ${path.length ? `<ol class="org-path-list">${path.map(renderOrgPathNode).join("")}</ol>` : ""}
      <div class="org-blueprint-grid">
        ${contacts.length ? renderOrgContactPanel(contacts) : ""}
        ${rules.length || missing.length ? renderOrgRulePanel(rules, missing) : ""}
      </div>
    </div>
  `;
}

function renderOrgPathNode(item) {
  return `
    <li>
      <strong>${escapeHtml(item.stage || "")}</strong>
      <span>${escapeHtml(item.owner || "")}</span>
      <p>${escapeHtml(item.signal || "")}${renderSourceIds(item.source_ids || [])}</p>
    </li>
  `;
}

function renderOrgContactPanel(items) {
  return `
    <article class="org-contact-panel">
      <h4>优先触点</h4>
      <div class="org-contact-list">
        ${items.map(renderOrgContactItem).join("")}
      </div>
    </article>
  `;
}

function renderOrgContactItem(item) {
  return `
    <div class="org-contact-item">
      <div>
        <strong>${escapeHtml(item.role || "")}</strong>
        <span>${escapeHtml(item.status || "")}</span>
      </div>
      <p>${escapeHtml(item.evidence || "")}${renderSourceIds(item.source_ids || [])}</p>
      <em>${escapeHtml(item.action || "")}</em>
    </div>
  `;
}

function renderOrgRulePanel(rules, missing) {
  return `
    <article class="org-rule-panel">
      <h4>决策规则与待补信息</h4>
      ${rules.length ? `<ul class="org-rule-list">${rules.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
      ${missing.length ? `<div class="org-missing-list">${missing.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
    </article>
  `;
}

function renderOrgDecisionCategory(section) {
  const rows = section.rows || [];
  return `
    <article class="org-decision-category">
      <h3>${escapeHtml(section.category || "")}</h3>
      <div class="org-decision-table">
        ${rows.map(renderOrgDecisionRow).join("")}
      </div>
    </article>
  `;
}

function renderOrgDecisionRow(item) {
  return `
    <div class="org-decision-row">
      <strong>${escapeHtml(item.field)}</strong>
      <span>${escapeHtml(item.value)}</span>
      <em>${escapeHtml(item.description || "")}${renderSourceIds(item.source_ids || [])}</em>
    </div>
  `;
}

function renderStrategyNeeds(sections) {
  if (!sections.length) return "";
  const rowCount = sections.reduce((total, section) => total + (section.rows || []).length, 0);
  return `
    <section class="strategy-needs-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">发展战略与需求模块</p>
          <h3>发展战略与需求画像</h3>
        </div>
        <span>${rowCount} 个字段 · 对齐 Excel 大纲</span>
      </div>
      <div class="strategy-needs-grid">
        ${sections.map(renderStrategyNeedsCategory).join("")}
      </div>
    </section>
  `;
}

function renderStrategyNeedsCategory(section) {
  const rows = section.rows || [];
  return `
    <article class="strategy-needs-category">
      <h3>${escapeHtml(section.category || "")}</h3>
      <div class="strategy-needs-table">
        ${rows.map(renderStrategyNeedsRow).join("")}
      </div>
    </article>
  `;
}

function renderStrategyNeedsRow(item) {
  return `
    <div class="strategy-needs-row">
      <strong>${escapeHtml(item.field)}</strong>
      <span>${escapeHtml(item.value)}</span>
      <em>${escapeHtml(item.description || "")}${renderSourceIds(item.source_ids || [])}</em>
    </div>
  `;
}

function renderPainOpportunities(sections) {
  if (!sections.length) return "";
  const rowCount = sections.reduce((total, section) => total + (section.rows || []).length, 0);
  return `
    <section class="pain-opportunities-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">痛点与机会模块</p>
          <h3>痛点与机会画像</h3>
        </div>
        <span>${rowCount} 个字段 · 对齐 Excel 大纲</span>
      </div>
      <div class="pain-opportunities-grid">
        ${sections.map(renderPainOpportunityCategory).join("")}
      </div>
    </section>
  `;
}

function renderPainOpportunityCategory(section) {
  const rows = section.rows || [];
  return `
    <article class="pain-opportunity-category">
      <h3>${escapeHtml(section.category || "")}</h3>
      <div class="pain-opportunity-table">
        ${rows.map(renderPainOpportunityRow).join("")}
      </div>
    </article>
  `;
}

function renderPainOpportunityRow(item) {
  return `
    <div class="pain-opportunity-row">
      <strong>${escapeHtml(item.field)}</strong>
      <span>${escapeHtml(item.pain || item.value || "")}</span>
      <b>${escapeHtml(item.opportunity || "")}</b>
      <em>${escapeHtml(item.description || "")}${renderSourceIds(item.source_ids || [])}</em>
      ${renderPainSchneiderMatch(item)}
    </div>
  `;
}

function renderPainSchneiderMatch(item) {
  if (!item.schneider_advantage && !item.schneider_playbook && !item.playbook_output) return "";
  return `
    <div class="pain-schneider-match">
      <article>
        <small>施耐德对应优势</small>
        <p>${escapeHtml(item.schneider_advantage || "")}</p>
      </article>
      <article>
        <small>${escapeHtml(item.playbook_stage || "具体打法")}</small>
        <p>${escapeHtml(item.schneider_playbook || "")}</p>
        ${item.playbook_output ? `<em>输出物：${escapeHtml(item.playbook_output)}</em>` : ""}
      </article>
    </div>
  `;
}

function renderRiskAssessment(sections) {
  if (!sections.length) return "";
  const rowCount = sections.reduce((total, section) => total + (section.rows || []).length, 0);
  return `
    <section class="risk-assessment-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">风险评估模块</p>
          <h3>风险评估画像</h3>
        </div>
        <span>${rowCount} 个字段 · 对齐 Excel 大纲</span>
      </div>
      <div class="risk-assessment-grid">
        ${sections.map(renderRiskAssessmentCategory).join("")}
      </div>
    </section>
  `;
}

function renderRiskAssessmentCategory(section) {
  const rows = section.rows || [];
  return `
    <article class="risk-assessment-category">
      <h3>${escapeHtml(section.category || "")}</h3>
      <div class="risk-assessment-table">
        ${rows.map(renderRiskAssessmentRow).join("")}
      </div>
    </article>
  `;
}

function renderRiskAssessmentRow(item) {
  return `
    <div class="risk-assessment-row">
      <strong>${escapeHtml(item.field)}</strong>
      <span>${escapeHtml(item.value)}</span>
      <em>${escapeHtml(item.description || "")}${renderSourceIds(item.source_ids || [])}</em>
    </div>
  `;
}

function renderBasicInfoRow(item) {
  return `
    <div class="basic-info-row">
      <strong>${escapeHtml(item.field)}</strong>
      <span>${escapeHtml(item.value)}</span>
      <em>${escapeHtml(item.description || "")}${renderSourceIds(item.source_ids || [])}</em>
    </div>
  `;
}

function renderSourceIds(sourceIds) {
  if (!sourceIds.length) return "";
  return ` · ${sourceIds.map((sourceId) => citationLink(`【${sourceId}】`, sourceId)).join("")}`;
}

function renderPortrait(portrait) {
  if (!portrait || !Object.keys(portrait).length) return "";
  return `
    <section class="portrait-panel">
      <div class="portrait-hero">
        <div>
          <p class="eyebrow">企业洞察画像</p>
          <h3>${escapeHtml(portrait.headline || "企业洞察画像")}</h3>
          <p>${escapeHtml(portrait.business_role || "")}</p>
        </div>
        <div class="portrait-tags">
          ${(portrait.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
        </div>
      </div>
      <div class="portrait-grid">
        ${portraitCard("经营策略", portrait.relationship_strategy)}
        ${portraitListCard("核心需求", portrait.needs)}
        ${portraitListCard("主要痛点", portrait.pain_points)}
      </div>
      <div class="portrait-grid two">
        ${portraitDecisionChain(portrait.decision_chain || [])}
        ${portraitListCard("下一步访谈问题", portrait.next_questions)}
      </div>
    </section>
  `;
}

function portraitCard(title, text) {
  return `
    <article class="portrait-card">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(text || "")}</p>
    </article>
  `;
}

function portraitListCard(title, items) {
  const safeItems = items || [];
  return `
    <article class="portrait-card">
      <h3>${escapeHtml(title)}</h3>
      ${
        safeItems.length
          ? `<ul>${safeItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
          : `<p class="empty-state">暂无。</p>`
      }
    </article>
  `;
}

function portraitDecisionChain(items) {
  return `
    <article class="portrait-card decision-card">
      <h3>决策链画像</h3>
      ${
        items.length
          ? `<div class="decision-chain">${items
              .map(
                (item) => `
                  <div>
                    <strong>${escapeHtml(item.role)}</strong>
                    <span>${escapeHtml(item.focus)}</span>
                  </div>
                `,
              )
              .join("")}</div>`
          : `<p class="empty-state">暂无。</p>`
      }
    </article>
  `;
}

function renderKpi(item) {
  return `
    <div class="kpi-item">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <small>${escapeHtml(item.note || "")}</small>
    </div>
  `;
}

function renderModuleCoverage(item) {
  const pct = Math.max(0, Math.min(100, Number(item.completion || 0)));
  return `
    <div class="module-row">
      <div>
        <strong>${escapeHtml(item.name)}</strong>
        <span>${item.field_count} 字段 · 内部 ${item.internal_count} · 访谈 ${item.interview_count}</span>
      </div>
      <div class="progress-cell" title="报告中显性写入或明确标注缺口的字段比例">
        <div class="progress-track"><span style="width: ${pct}%"></span></div>
        <em>${pct}%</em>
      </div>
    </div>
  `;
}

function renderOpportunityList(items) {
  if (!items.length) return `<div class="empty-state">暂无机会地图。</div>`;
  return `
    <div class="opportunity-list">
      ${items
        .map((item) => {
          const priority = item["优先级"] || "P";
          const title = item["机会主题"] || item["目标"] || "";
          const target = item["目标主体/部门"] || item["目标部门/角色"] || item["目标对象"] || "";
          const action = item["下一步动作"] || item["推荐切入方案"] || item["推荐方案"] || "";
          return `
            <article class="opportunity-item">
              <span class="priority">${escapeHtml(priority)}</span>
              <div>
                <h3>${escapeHtml(title)}</h3>
                <p>${escapeHtml(target)}</p>
                <small>${escapeHtml(action)}</small>
              </div>
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderRiskList(items) {
  if (!items.length) return `<p class="empty-state">暂无风险摘要。</p>`;
  return `<ul class="risk-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function statusTag(label, value, tone) {
  return `<span class="status-tag ${tone}"><small>${escapeHtml(label)}</small>${escapeHtml(value)}</span>`;
}

function citationLink(label, sourceId) {
  const source = state.project?.source_references?.[sourceId];
  if (!source || !isExternalUrl(source.url)) return label;
  const title = [source.title, source.publisher, source.date].filter(Boolean).join(" · ");
  return `<a class="citation-link" href="${escapeAttr(source.url)}" target="_blank" rel="noreferrer" title="${escapeAttr(title)}">${label}</a>`;
}

function isExternalUrl(value) {
  return /^https?:\/\//.test(String(value || ""));
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(text) {
  return escapeHtml(text).replace(/'/g, "&#39;");
}

function cleanModuleName(name) {
  return String(name || "").replace(/^\d+\.\s*/, "");
}

loadStatus().catch(() => {
  dashboardBoard.textContent = "数据读取失败";
});
