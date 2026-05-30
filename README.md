# 城市产业深度研究报告生成器

这个项目把“地级市支柱产业与新兴产业双轮驱动研究报告”的复杂大纲，沉淀成一个可复用 CLI 功能。输入地级市名称后，它会生成：

- 权威来源检索计划：政府官网、统计公报、发改/工信/商务/税务/园区、官方媒体、官方微信、交易所/上市公司公告等。
- 证据库模板：所有关键结论必须绑定来源编号，避免凭空生成。
- 深度研究提示词：严格按支柱产业、新兴产业、企业榜单、电气业务机会等章节输出。
- 报告 Markdown 模板：可直接渲染成研究报告初稿。
- 企业表格 CSV 模板：覆盖支柱产业企业、新兴产业企业、上市公司、外商投资企业、纳税/百强企业。
- 证据完整性校验：提醒缺失的官方来源类别。

## 快速开始

启动交互界面：

```bash
PYTHONPATH=src python3 -m city_industry_research web --host 127.0.0.1 --port 8787
```

浏览器打开：

```text
http://127.0.0.1:8787
```

界面支持输入省份、地级市、报告年度、模型。默认流程会自动拆解研究大纲、检索政府官网/统计/发改/工信/商务/税务/官方媒体/交易所等来源、抓取网页正文、生成证据库，再生成报告。补充官方来源链接只是可选增强，不是必填项。

若设置了 `OPENAI_API_KEY`，系统会基于自动发现的证据生成正文，并可启用 OpenAI Responses API 的 Web Search 继续补足来源缺口。未手动填写模型时，默认使用 `gpt-5.5`。

```bash
PYTHONPATH=src python3 -m city_industry_research init --city 无锡市 --province 江苏省 --out outputs/wuxi
```

生成目录示例：

```text
outputs/wuxi/
  00_source_discovery_plan.md
  01_evidence_template.json
  02_llm_research_prompt.md
  03_report_template.md
  tables/
    pillar_enterprises_top10.csv
    emerging_enterprises_top10.csv
    listed_companies_top10.csv
    foreign_invested_enterprises_top10.csv
    local_top20_enterprises.csv
```

如果已经整理了证据库，可以校验和渲染：

```bash
PYTHONPATH=src python3 -m city_industry_research validate --evidence outputs/wuxi/01_evidence_template.json
PYTHONPATH=src python3 -m city_industry_research render --city 无锡市 --province 江苏省 --evidence outputs/wuxi/01_evidence_template.json --out outputs/wuxi/report.md
```

如果已经收集了一批官方链接，可先抓取成证据库：

```bash
PYTHONPATH=src python3 -m city_industry_research ingest --city 无锡市 --province 江苏省 --urls official_urls.txt --tag industry_plan --tag official_media --out outputs/wuxi/evidence.from_urls.json
```

如果配置了 OpenAI API，也可以用证据库直接生成报告正文：

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-5.5
PYTHONPATH=src python3 -m city_industry_research generate --city 无锡市 --province 江苏省 --evidence outputs/wuxi/01_evidence_template.json --out outputs/wuxi/report.generated.md --model "$OPENAI_MODEL"
```

也可以在 CLI 中启用联网搜索：

```bash
PYTHONPATH=src python3 -m city_industry_research generate --city 无锡市 --province 江苏省 --evidence outputs/wuxi/01_evidence_template.json --out outputs/wuxi/report.generated.md --model "$OPENAI_MODEL" --web-search
```

## 邮件与 Google Docs

Web 界面提供两种导出动作：

- 邮件：如果配置了 `SMTP_HOST` 和 `SMTP_FROM`，会直接通过 SMTP 发送；否则会在 `outputs/export_requests/` 中生成邮件请求 JSON，供 Codex 使用 Gmail 连接器创建草稿或发送。
- Google Docs：会在 `outputs/export_requests/` 中生成 Google Docs 请求 JSON，供 Codex 使用 Google Drive 连接器创建文档。

可选 SMTP 环境变量：

```bash
export SMTP_HOST=smtp.example.com
export SMTP_PORT=587
export SMTP_FROM=sender@example.com
export SMTP_USER=sender@example.com
export SMTP_PASSWORD=...
```

## 研究口径

本工具默认坚持三条规则：

1. 优先使用地级市政府官网、统计局、发改委、工信局、商务局、税务局、国资委、市场监管局、各区县/开发区官网、官方媒体和官方微信公众号。
2. 对上市公司市值、营业收入、境外布局等可补充交易所公告、公司年报、巨潮资讯等官方披露渠道，并在报告中标注口径和日期。
3. 对无法从权威来源确认的数据，报告必须标记为“待核验/来源缺口”，不能编造。

## 盘厂大客户洞察报告生成器

本项目也新增了面向施耐德电气盘厂客户部的客户洞察生成器。它把 `AI洞察报告框架.xlsx` 中的 9 个模块沉淀为标准字段库：基础信息、业务能力、供应链与采购、客户资源、销售与市场、组织架构与决策链、发展战略与需求、痛点与机会、风险评估。

初始化一个客户洞察项目：

```bash
PYTHONPATH=src python3 -m switchgear_customer_insight init --customer "浙江正泰电器股份有限公司" --out outputs/chint_electric_2026/project
```

启动网站工作台：

```bash
PYTHONPATH=src python3 -m switchgear_customer_insight web --host 127.0.0.1 --port 8790
```

浏览器打开：

```text
http://127.0.0.1:8790
```

生成目录包括：

```text
00_source_plan.md       # 公开来源与内部资料补充计划
01_field_register.csv   # 附件框架字段登记表
02_research_prompt.md   # 可交给大模型或研究员的深度研究提示词
03_report_template.md   # 逐字段报告模板
```

也可以单独生成提示词或模板：

```bash
PYTHONPATH=src python3 -m switchgear_customer_insight prompt --customer "客户全称" --out outputs/customer_prompt.md
PYTHONPATH=src python3 -m switchgear_customer_insight template --customer "客户全称" --out outputs/customer_template.md
```
