# 施耐德盘厂企业洞察研究工作台

这是一个面向施耐德电气盘厂客户部/大客户研究场景的本地网站项目，用于沉淀和展示企业深度洞察。项目已将 `AI洞察报告框架.xlsx` 中的 9 大模块转化为可点击、可下载、可追溯来源的企业洞察看板。

当前内置企业包括：

- 浙江正泰电器股份有限公司
- 江苏中环电气集团有限公司
- 福州天宇电气股份有限公司
- 部分油气化工 KA 研究对象

## 核心功能

- 企业下拉选择：选择企业后直接展示对应洞察内容。
- 9 大模块画像：基础信息、业务能力、供应链与采购、客户资源、销售与市场、组织架构与决策链、发展战略与需求、痛点与机会、风险评估。
- 摘要页签：从 9 大模块提炼企业洞察摘要。
- 信息补充页签：记录仍需内部 CRM、销售台账、访谈或项目资料补充的信息。
- 参考数据源页签：展示公开来源，并支持点击跳转。
- Word/Markdown 下载：可下载报告文档。
- Windows 便携启动：支持 Python、PowerShell、bat 多种启动方式。

## 运行环境

- Python 3.9 或更高版本
- 浏览器：Chrome、Edge、Firefox、Safari 均可
- 不需要额外 Python 依赖

## 最简单启动方式

在项目根目录运行：

```bash
python start.py
```

如果系统命令是 `python3`：

```bash
python3 start.py
```

浏览器打开：

```text
http://127.0.0.1:8790/
```

## 常用启动参数

指定端口：

```bash
python start.py --port 8791
```

局域网共享模式：

```bash
python start.py --lan
```

启动后，其他电脑可访问：

```text
http://本机IP:8790/
```

不自动打开浏览器：

```bash
python start.py --no-browser
```

## Windows 启动方式

解压发布包后，可直接双击：

```text
start_windows.bat
```

局域网共享：

```text
start_lan.bat
```

## PowerShell 启动方式

在解压目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_powershell.ps1
```

局域网共享：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_powershell_lan.ps1
```

## Python 模块启动方式

也可以使用模块入口：

```bash
PYTHONPATH=src python -m switchgear_customer_insight web --host 127.0.0.1 --port 8790
```

列出 9 大框架模块：

```bash
PYTHONPATH=src python -m switchgear_customer_insight framework
```

初始化单个企业研究项目：

```bash
PYTHONPATH=src python -m switchgear_customer_insight init --customer "浙江正泰电器股份有限公司" --out outputs/chint_electric_2026/project
```

生成研究提示词：

```bash
PYTHONPATH=src python -m switchgear_customer_insight prompt --customer "客户全称" --out outputs/customer_prompt.md
```

生成报告模板：

```bash
PYTHONPATH=src python -m switchgear_customer_insight template --customer "客户全称" --out outputs/customer_template.md
```

## 发布包

已生成的 Windows/Python 启动版压缩包位于：

```text
outputs/switchgear_enterprise_insight_python_start.zip
```

解压后可使用：

```bash
python start.py
```

或：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_powershell.ps1
```

## 目录说明

```text
src/switchgear_customer_insight/        # 企业洞察网站、数据、报告和下载逻辑
src/switchgear_customer_insight/static/ # 前端页面、样式和交互脚本
outputs/chint_electric_2026/            # 正泰电器报告和来源登记
outputs/zhonghuan_electric_2026/        # 中环电气报告和来源登记
outputs/tianyu_electric_2026/           # 天宇电气报告和来源登记
outputs/switchgear_customer_web/        # 网站运行时生成的项目文件
packaging/                              # Windows/PowerShell 发布脚本
tests/                                  # 自动化测试
```

## 数据和来源

每家企业报告均配有 `source_registry.md`，用于维护来源编号和可点击链接。页面中的 `S1`、`SE1`、`ZH1` 等引用会根据来源登记表自动生成链接。

## 测试

运行核心测试：

```bash
PYTHONPATH=src pytest tests/test_webapp.py tests/test_switchgear_customer_insight.py
```

如果本机没有 pytest，可使用 `uv` 临时运行：

```bash
PYTHONPATH=src uv run --with pytest pytest tests/test_webapp.py tests/test_switchgear_customer_insight.py
```

## 附属工具：城市产业研究

仓库中仍保留早期的城市产业深度研究工具，入口为：

```bash
PYTHONPATH=src python -m city_industry_research web --host 127.0.0.1 --port 8787
```

该工具用于地级市产业研究报告生成，与当前企业洞察工作台相互独立。
