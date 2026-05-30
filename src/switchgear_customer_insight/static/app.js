const state = {
  project: null,
  framework: [],
  selectedModuleIndex: 0,
};

const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => Array.from(document.querySelectorAll(selector));

const customerForm = qs("#customerForm");
const customerSelect = qs("#customerSelect");
const moduleList = qs("#moduleList");
const frameworkCount = qs("#frameworkCount");
const dashboardBoard = qs("#dashboardBoard");
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
  framework.forEach((item) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${escapeHtml(cleanModuleName(item.name))}</span><strong>${item.field_count} 字段</strong>`;
    moduleList.appendChild(li);
  });
}

qsa(".view-tab").forEach((button) => {
  button.addEventListener("click", () => {
    const view = button.dataset.view;
    qsa(".view-tab").forEach((item) => item.classList.toggle("is-active", item === button));
    qs("#dashboardView").classList.toggle("is-hidden", view !== "dashboard");
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
  dashboardBoard.classList.add("empty-state");
  dashboardBoard.textContent = "正在加载客户 360 洞察画像...";

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
  renderDashboard(project);
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
    ${renderSourceCoverage(project)}
    ${renderSelectedModulePanel(dashboard, portrait, selectedIndex)}
    <section class="customer-360-layout">
      <aside class="customer-dossier-column">
        ${renderCustomerDossier(project, dashboard, portrait)}
      </aside>
      <main class="insight-center-column">
        ${renderInsightCardStack(dashboard, portrait)}
      </main>
      <aside class="action-risk-column">
        ${renderActionRiskRail(dashboard, portrait)}
      </aside>
    </section>
  `;
}

function renderCustomerDossier(project, dashboard, portrait) {
  const profile = dashboard.profile || {};
  const basicInfo = dashboard.basic_info || [];
  const certifications = dashboard.certifications || [];
  const scaleFinance = dashboard.scale_finance || {};
  return `
    <section class="account-hero-card">
      <p class="eyebrow">Vitally Account Profile</p>
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
    ${renderDossierCard("客户档案", basicInfo, ["企业名称", "企业性质", "成立时间", "注册资本", "注册地址"], "Profile")}
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
          <h3>客户健康层</h3>
        </div>
      </div>
      <div class="health-grid">
        ${renderHealthMetric("客户价值", profile.opportunity_level || "待评估", profile.recommended_focus || "", valueTone)}
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
      ${renderInsightDetails("03 供应链与采购模块", "15 字段 · 施耐德合作、竞品采购、供应商", renderSupplyProcurement(dashboard.supply_procurement || []), true)}
      ${renderInsightDetails("04 客户资源模块", "8 字段 · 客户结构、客户关系", renderCustomerResources(dashboard.customer_resources || []))}
      ${renderInsightDetails("05 销售与市场模块", "11 字段 · 销售体系、市场覆盖、价格策略", renderSalesMarket(dashboard.sales_market || []))}
      ${renderInsightDetails("06 组织架构与决策链模块", "12 字段 · 关键人、部门和流程", renderOrgDecision(dashboard.org_decision || []))}
      ${renderInsightDetails("07 发展战略与需求模块", "13 字段 · 发展、数字化、绿色低碳、电气升级", renderStrategyNeeds(dashboard.strategy_needs || []))}
      ${renderInsightDetails("08 痛点与机会模块", "10 字段 · 业务、技术、市场痛点转行动机会", renderPainOpportunities(dashboard.pain_opportunities || []))}
    </section>
  `;
}

function renderSummaryInsightCard(dashboard, portrait) {
  return `
    <article class="summary-insight-card">
      <div>
        <p class="eyebrow">Executive Brief</p>
        <h3>${escapeHtml(portrait.headline || "客户洞察摘要")}</h3>
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
          <h3>大客户洞察 9 模块地图</h3>
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
          <h3>多源数据覆盖</h3>
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
  if (/chint\.net|chint\.com|xjgc\.com|cee-group|官网|投资者关系|联系我们|集团官网/.test(text)) return "企业官网/官方IR";
  if (/gov\.cn|ggzy|公共资源|水利局|科技厅|政府|高新技术企业|公示/.test(text)) return "政府/公共资源";
  if (/sse|szse|cninfo|新浪财经|东方财富|证券|券商|研报|公告|股票|finance/.test(text)) return "证券公告/券商研究";
  if (/中车|电建|核电|行业|协会|招投标|中标|候选|采购|项目/.test(text)) return "行业权威/项目平台";
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
    () => renderOrgDecision(dashboard.org_decision || []),
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
  if (name === "基础信息模块") return "左侧客户档案";
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

function renderOrgDecision(sections) {
  if (!sections.length) return "";
  const rowCount = sections.reduce((total, section) => total + (section.rows || []).length, 0);
  return `
    <section class="org-decision-panel">
      <div class="section-row">
        <div>
          <p class="eyebrow">组织架构与决策链模块</p>
          <h3>组织与决策链画像</h3>
        </div>
        <span>${rowCount} 个字段 · 对齐 Excel 大纲</span>
      </div>
      <div class="org-decision-grid">
        ${sections.map(renderOrgDecisionCategory).join("")}
      </div>
    </section>
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
          <p class="eyebrow">客户洞察画像</p>
          <h3>${escapeHtml(portrait.headline || "客户洞察画像")}</h3>
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
