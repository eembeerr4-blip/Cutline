# Cutline

**Turn a link or a video file into a ready-to-post clip: 1920x1080, 30 fps, burned-in subtitles, normalized sound, plus a post text written by Claude.**
Windows desktop app. Everything runs locally on your PC (speech recognition on your NVIDIA GPU). The interface is in Russian.

[Русская версия ниже](#cutline-по-русски)

## How it works

1. **Source.** Paste a YouTube / X link or choose a file. Cutline downloads it and transcribes the speech locally (faster-whisper, `large-v3-turbo`).
2. **Moment.** Press "Скопировать всю расшифровку" ("Copy the whole transcript"), paste it into any Claude chat. The copied text already contains the answer template and your writing rules. Paste Claude's answer back: it holds the clip boundaries, the post text, a Russian translation and subtitle punctuation.
3. **Montage.** One button builds the clip (cut, fit to 1920x1080, subtitles, loudness, fades). A fast low-quality **preview** is available before the final build.
4. **Text.** The post is checked against the platform rules and saved next to the video in `Готовые видео`.

Claude (free tier is enough) only finds the video and writes the text. Everything else happens in the app.

## Requirements

- Windows 10/11
- NVIDIA GPU with 6+ GB VRAM recommended (without it transcription runs on CPU and is much slower)
- Python 3.12 (`py -3.12`), about 6 GB of free disk space
- Node.js (installed by the installer through winget if missing; yt-dlp needs it for YouTube)

## Install

1. Download the repository as a ZIP (or `git clone`) and unpack it, for example to `C:\Cutline`. Avoid network drives.
2. Run **`install.bat`**. It creates a virtual environment, installs the pinned packages, downloads FFmpeg and the speech model (about 1.6 GB), builds `Cutline.exe` and puts a shortcut on the desktop.
3. Start Cutline from the shortcut or `Cutline.bat`.

Settings (output folder, speech model, default subtitles) are in the "Система" tab. Platform profiles live in `profiles/` and the writing rules for Claude in `rules/writing_rules.md`: replace them with your own style.

## Adding another platform

Copy `profiles/x.json`, change size, clip length, subtitle style and `text_check` (see `clipper/textcheck.py`), and select it with `"profile"` in `config.json`.

## Privacy

No accounts, no telemetry. The app talks only to the sites you give it (through yt-dlp) and to Hugging Face once to download the model. The local server listens on `127.0.0.1` and is protected by a session token. Your projects stay in the `data` folder.

## Legal

- MIT license (see `LICENSE`). Third-party components: `docs/THIRD_PARTY.md`.
- Downloading videos can violate the terms of the site you download from. You are responsible for what you download and publish and for having the rights to it.

## Tests

```
.venv\Scripts\python.exe -m unittest discover -s tests
```

---

# Cutline по-русски

**Из ссылки или видеофайла делает готовый клип 1920x1080, 30 к/с, с субтитрами, ровным звуком и текстом поста от Claude.** Приложение для Windows, всё считается на твоём компьютере (расшифровка на видеокарте NVIDIA).

**Как пользоваться.**
1. «Источник»: вставь ссылку (YouTube, X) или выбери файл. Резка и расшифровка идут локально.
2. «Момент»: нажми «Скопировать всю расшифровку», вставь в чат с Claude (хватит бесплатного). В скопированном тексте уже есть шаблон ответа и правила. Ответ Claude вставь обратно: в нём границы клипа, пост, перевод и знаки препинания для субтитров.
3. «Монтаж»: «Предпросмотр» (быстро, низкое качество) и «Собрать ролик».
4. «Текст»: проверка поста и сохранение рядом с видео в папке «Готовые видео».

**Установка.** Скачай ZIP, распакуй (например в `C:\Cutline`), запусти `install.bat`, дальше запускай ярлык Cutline на рабочем столе. Нужны Windows 10/11, Python 3.12, видеокарта NVIDIA (желательно от 6 ГБ), около 6 ГБ места. Свои правила текста: `rules/writing_rules.md`, другие платформы: `profiles/`.

**Важно.** Скачивание видео может нарушать правила сайта, откуда оно скачивается: ответственность за это на пользователе. Лицензия MIT.
