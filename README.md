# Local Screen AI

A native Windows desktop assistant (PySide6) that captures your screen **only when you press a shortcut**,
extracts text with **local Tesseract OCR**, and sends it to a **local Ollama model** when **you** submit.
No cloud AI, no remote backend, no paid subscription.

```
capture (hotkey) → OCR (Tesseract) → queue + edit text → submit (hotkey) → Ollama (localhost) → answer → follow-ups
```

## Features
- Global shortcuts (all configurable): `Ctrl+Shift+S` capture · `Ctrl+Shift+Enter` submit · `Ctrl+Shift+Space` show/hide · `Ctrl+Shift+Backspace` clear queue (with confirmation).
- Screenshot queue: thumbnail, timestamp, size, OCR status (Pending/Processing/Completed/Failed), text preview, preview/remove, select, reorder.
- Editable OCR text, copy, retry OCR, clear text. No fake OCR confidence is shown.
- Three modes: **Explain Screen**, **Coding Helper**, **General Assistant**.
- Input modes: **Text** (OCR only, default) · **Vision** · **Hybrid** (optional, slower).
- Streaming Markdown answers, copy, retry, stop, follow-up questions without recapturing.
- Pause Capture, always-on-top toggle, tray icon, Clear All.
- Settings: models, shortcuts, monitor, OCR language/preprocessing, image size, context length, response tokens, timeout, queue limit, theme.

## Privacy & security
- All OCR and inference are local. The Ollama endpoint is restricted to `localhost`/`127.0.0.1` (config values pointing elsewhere are rejected).
- Cloud-hosted Ollama models (names ending in `:cloud`/`-cloud`) are **hidden and never used**.
- No telemetry, no logging of screenshots/prompts, nothing saved except non-sensitive preferences in `%APPDATA%\LocalScreenAI\config.json`.
- Screenshots live in memory only. No periodic/automatic capture, no automatic submission, no autostart, no keystroke/click injection, no execution of AI output.
- Models are only downloaded after you confirm.
- Local inference does not make your computer secure: **the security of your computer and installed software remains your responsibility.**
- Capture is always visible: status line, tray notification, Pause button. Do not use this tool to bypass exams/proctoring rules.

## Setup (Windows)

1. **Python** (3.11 recommended):
   ```powershell
   py -3.11 --version
   ```
   Install from https://www.python.org/downloads/ if missing.
2. **Virtual environment**:
   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3. **Python dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```
4. **Tesseract OCR** (not a pip package):
   ```powershell
   winget install UB-Mannheim.TesseractOCR
   ```
   or download the installer from https://github.com/UB-Mannheim/tesseract/wiki. Default path: `C:\Program Files\Tesseract-OCR\tesseract.exe`.
5. **Tesseract path**: auto-detected from `PATH` and the default install folders. Otherwise set it in *Settings → Capture & OCR → Tesseract path*. Extra languages: install the language data and set e.g. `eng+fra`.
6. **Ollama**: https://ollama.com/download (or `winget install Ollama.Ollama`). Make sure it is running (tray icon, or `ollama serve`).
7. **Small text model** (needs internet once, ~1.9 GB):
   ```powershell
   ollama pull qwen2.5:3b
   ```
   If it is too slow on your CPU, try a 1–2B model (`ollama pull qwen2.5:1.5b` or `llama3.2:1b`) and select it in Settings. Ollama chooses CPU/GPU backend automatically; the app forces nothing.
   If the model is missing, the app shows the exact command and asks before downloading.
8. **Run**:
   ```powershell
   python main.py
   ```
9. **Tests**:
   ```powershell
   python -m pytest -q
   ```
10. **Optional vision model** (slow on CPU, ~3 GB): `ollama pull qwen2.5vl:3b`, then set Input to *Vision* or *Hybrid*. The app checks that the model supports images and warns about speed.
11. **Package** (model files stay outside the exe; Tesseract and Ollama must be installed on the target PC):
    ```powershell
    pyinstaller --noconfirm --windowed --name LocalScreenAI main.py
    ```
    Output: `dist\LocalScreenAI\LocalScreenAI.exe`.

Internet is needed only to install software and download models. Afterwards the app works fully offline.

### Hardware tuning (Ryzen 5 7520U, 16 GB)
Defaults: context 4096, response 512 tokens, temperature 0.2, OCR image ≤ 2560 px, vision image ≤ 1024 px, max 5 screenshots/submission. Lower context/response tokens and screenshot count for faster answers. Only one OCR job runs at a time; OCR and AI run in background threads.

### Known limitations
- Global hotkeys use `pynput`, which observes keys but cannot detect that another app already owns a combination (it detects duplicates within this app). Change shortcuts in Settings if a conflict occurs.
- Capturing from elevated (admin) windows may require running this app as admin for hotkeys to be seen.
- Protected/DRM content may capture as black.
- OCR quality depends on the screen; always review the text. Small models can be wrong.

## Project layout
```
main.py            app/config.py  app/models.py
app/capture/       screen_capture.py, image_processor.py
app/ocr/           ocr_engine.py, text_preprocessor.py
app/ai/            ollama_client.py, prompts.py
app/shortcuts/     shortcut_manager.py
app/services/      session_manager.py
app/ui/            floating_window.py (view), main_window.py (controller), screenshot_queue.py, settings_dialog.py, widgets.py
tests/             unit + headless UI smoke tests (Ollama/OCR mocked)
```

## Manual test checklist
Tick each when verified on your machine.

- [ ] First launch: window appears, tray icon shows, status pill shows Ollama state, shortcuts listed.
- [ ] OCR installation: with Tesseract missing a clear install message appears; after install a capture completes OCR.
- [ ] Screenshot capture: `Ctrl+Shift+S` while another app is focused adds an item (our window isn't in the shot).
- [ ] Multiple queued screenshots: capture 3; reorder, deselect one, remove one.
- [ ] OCR preview & editing: select an item, edit text; queue preview updates; Retry OCR and Clear text work.
- [ ] Text submission: `Ctrl+Shift+Enter` streams an answer; only selected, edited text is used.
- [ ] Follow-up questions: ask without recapturing; context is kept.
- [ ] All three modes: Explain Screen, Coding Helper, General Assistant produce different styles.
- [ ] Switching models: change in Settings, status/model label update.
- [ ] Missing Ollama: stop Ollama → red status and start instructions.
- [ ] Missing model: select a non-installed model → exact `ollama pull` command + confirmation before download.
- [ ] Pausing capture: shortcut and button do nothing while paused; resume works.
- [ ] Clearing all data: Clear all / `Ctrl+Shift+Backspace` (confirms) / tray "Clear all data" / Clear conversation.
- [ ] Exit during inference: press Exit while generating; app closes without hanging.
- [ ] Offline operation: disconnect network; capture → OCR → answer still works.
- [ ] Shortcut change: set a new capture shortcut in Settings; old one stops, new one works; duplicates are rejected.
- [ ] Vision/Hybrid (optional): warning shown; text-only model is rejected.
