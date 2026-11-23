# Сторонние компоненты и лицензии

Код чужих проектов копировать можно только под MIT/Apache/BSD, с указанием источника. Чужой код не копировался: библиотеки ставятся через pip.

| Компонент | Версия | Лицензия | Для чего |
|---|---|---|---|
| yt-dlp (+ yt-dlp-ejs) | 2026.10.26 / 0.8.0 | Unlicense (yt-dlp), MIT/ISC (ejs) | скачивание видео |
| faster-whisper | 1.2.1 | MIT | расшифровка |
| CTranslate2 | 4.8.5 | MIT | движок faster-whisper |
| nvidia-cublas-cu12, nvidia-cudnn-cu12 | 12.4.5.8 / 9.5.1.17 | NVIDIA CUDA Redistributable EULA | CUDA-библиотеки для CTranslate2 |
| pysubs2 | 1.9.1 | MIT | генерация ASS |
| rapidfuzz | см. requirements.lock | MIT | нечёткий поиск цитаты |
| FFmpeg | скачивается установщиком (сборка gyan.dev) | GPL/LGPL | резка и кодирование; в репозитории не хранится |
| pywebview (+ pythonnet, clr_loader, bottle, proxy_tools) | 6.2.1 / 3.2.1 / 0.3.1 / 0.13.4 / 0.1.0 | BSD-3 / MIT / MIT / MIT / BSD | собственное окно приложения на компоненте WebView2 из Windows (разрешено пользователем 2026-11-23) |
| Модель Whisper large-v3-turbo (Systran/faster-whisper-large-v3-turbo) | — | MIT | распознавание |

Идеи (не код) из: opensource-clipping (NaufalRizqullah, MIT), AutoClip (artbyjazi, MIT), OpenClip (linzzzzzz, MIT), clipper-skill (RealAdii, MIT), Prune и Toaster (MIT). Не использовать даже как код: SupoClip, Clips Kitty / clips-studio, podcli (AGPL), ViralCutter (GPL-3.0).

