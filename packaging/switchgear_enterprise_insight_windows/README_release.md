# Switchgear Enterprise Insight Workbench - Windows Portable Release

## Requirements

- Windows 10 / Windows 11
- Python 3.9 or later
- Edge, Chrome, or Firefox

No extra Python packages are required.

## Start Locally

1. Unzip the whole folder.
2. Double-click `start_windows.bat`.
3. Open `http://127.0.0.1:8790/` in your browser.

## Start with PowerShell

Open PowerShell in the unzipped folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_powershell.ps1
```

LAN mode:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_powershell_lan.ps1
```

## Start with Python

Open a terminal in the unzipped folder and run:

```powershell
python start.py
```

LAN mode:

```powershell
python start.py --lan
```

Use another port:

```powershell
python start.py --port 8791
```

## Share on LAN

1. Double-click `start_lan.bat`.
2. Find this computer's LAN IP address, for example `192.168.1.20`.
3. Other computers can open `http://192.168.1.20:8790/`.

If Windows Firewall asks for permission, allow Python to access the network.

## Included Data

- Chint Electric report and sources
- Zhonghuan Electric report and sources
- Tianyu Electric report and sources
- Built-in petrochemical KA data
- Word/Markdown download support
