# 🎵 AKX Downloader

Modern multimedia downloader built with Python, PyWebView and yt-dlp.

<img width="1983" height="793" alt="AKX Downloader banner" src="https://github.com/user-attachments/assets/3f4a1307-f241-4bb7-9c4d-a303e4dac93a" />

---

# ✨ Features

- 🎬 Video downloader
- 🎵 Audio extraction
- 📺 Supports multiple platforms
- 🖥️ Modern desktop interface
- ⚡ Fast downloads
- 🧠 Download history
- 🎧 Embedded media player
- 🌐 Local web-based UI
- 🔥 Built with Python + PyWebView

---

# 📸 Screenshots

## Main Interface

<img width="1212" height="806" alt="Main interface" src="https://github.com/user-attachments/assets/b66c2ebc-d9d3-4f2b-8fb2-de16daa46836" />

---

## History

<img width="1218" height="812" alt="Download history" src="https://github.com/user-attachments/assets/244ec835-2b89-481d-baa6-ecb55936ed85" />

---

# 🛠️ Technologies Used

- Python
- PyWebView
- yt-dlp
- HTML/CSS/JavaScript
- FFmpeg

---

# 📦 Installation

## Clone repository

```bash
git clone https://github.com/AkiraXleb/AKX_Downloader.git
```

---

## Install dependencies

```bash
py -3.10 -m pip install -r requirements.txt
```

FFmpeg must also be installed and available on `PATH` (see `requirements.txt`
for platform-specific instructions).

---

# 🚀 Run

```bash
py -3.10 akx_downloader.py
```

---

# 🧪 Tests

Unit tests currently cover `akx/naming.py` (filename/title cleanup logic):

```bash
py -3.10 -m unittest discover
```

---

# 🏗️ Build EXE

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Builds a `dist/AKX Downloader/` folder (onedir mode, default — fast startup).
Pass `-Modo onefile` for a single portable `.exe` instead (slower first
startup). See `build.ps1` for details.

---

# 📁 Project Structure

```plaintext
AKX_Downloader/
├── akx_downloader.py     # entry point
├── akx/                  # application package
│   ├── api/               # API class split into mixins (settings, downloads, ...)
│   ├── ui/index.html       # frontend (HTML/CSS/JS)
│   ├── naming.py            # filename/title cleanup (pure logic)
│   ├── telegram.py           # Telethon-based Telegram downloads
│   ├── ytdlp_engine.py        # hot-updatable yt-dlp loader
│   └── ...                     # settings, history, cookies, file server, etc.
├── tests/                # unit tests
├── build.ps1             # PyInstaller build script
├── make_icon.py          # PNG → multi-resolution .ico converter
└── requirements.txt
```

See `CLAUDE.md` for the full breakdown of each module.

---

# ⚠️ Notes

- FFmpeg is recommended for best compatibility.
- Some antivirus software may flag generated executables due to PyInstaller packaging.
- This project uses yt-dlp internally.

---

# ❤️ Credits

Created by AkiraXleb, with development assistance from
[Claude Code](https://claude.com/claude-code) (Anthropic) — used for
refactoring, test coverage and documentation.

Powered by:
- yt-dlp
- PyWebView
- Python

---

# 📜 License

MIT License
