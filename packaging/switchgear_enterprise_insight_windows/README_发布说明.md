# 施耐德盘厂企业洞察研究工作台 - Windows 发布版

## 运行环境

- Windows 10 / Windows 11
- Python 3.11 或更高版本
- 浏览器：Edge、Chrome 或 Firefox

本发布版不需要安装额外 Python 依赖。

## 启动方式

1. 解压整个文件夹到 Windows 电脑，例如：
   `D:\switchgear_enterprise_insight_windows_portable`
2. 双击 `启动项目.bat`
3. 浏览器打开：
   `http://127.0.0.1:8790/`

如果双击没有自动打开浏览器，可以手动复制上面的地址到浏览器。

## PowerShell 启动方式

如果希望用 PowerShell 启动，在解压后的目录空白处按住 `Shift` 并右键，选择“在终端中打开”，然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_powershell.ps1
```

局域网共享模式：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_powershell_lan.ps1
```

## 局域网共享

如果希望同一局域网内其他电脑访问：

1. 双击 `启动项目_局域网共享.bat`
2. 在启动电脑上查看本机 IP，例如 `192.168.1.20`
3. 其他电脑访问：
   `http://192.168.1.20:8790/`

Windows 防火墙可能会提示是否允许 Python 访问网络，请选择允许。

## 常见问题

### 提示找不到 Python

请安装 Python 3.11+，并勾选 `Add python.exe to PATH`。

下载地址：
https://www.python.org/downloads/windows/

### 端口 8790 被占用

关闭已有窗口，或编辑启动脚本，把 `8790` 改成其他端口，例如 `8791`。

### 数据文件在哪里

三家企业报告和来源登记在：

- `outputs/chint_electric_2026`
- `outputs/zhonghuan_electric_2026`
- `outputs/tianyu_electric_2026`

网站运行过程中生成的临时项目文件在：

- `outputs/switchgear_customer_web`

## 交付范围

此版本包含：

- 企业洞察网站
- 正泰电器、中环电气、天宇电气已有报告与来源
- 油气化工 KA 内置数据
- Word/Markdown 下载功能
- Windows 启动脚本
