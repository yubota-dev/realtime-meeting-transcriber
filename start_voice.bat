@echo off
chcp 65001 >nul
rem === ローカルLLM 音声対話 起動ランチャ ===
rem このファイルをプロジェクト直下（venv や meeting フォルダと同じ階層）に置く

rem --- 自分の置かれているフォルダへ移動（どこから起動しても安定）---
cd /d "%~dp0"

rem --- Ollama サーバが応答するか確認、ダメなら起動 ---
ollama list >nul 2>&1
if errorlevel 1 (
    echo Ollama を起動しています...
    start "" /min ollama serve
    timeout /t 3 >nul
)

rem --- 仮想環境を有効化 ---
if not exist "venv\Scripts\activate.bat" (
    echo [エラー] venv が見つかりません。先に初回セットアップを実行してください。
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

rem --- Python の出力文字化け対策 ---
set PYTHONIOENCODING=utf-8

rem --- 起動 ---
python -m meeting.voice_chat

echo.
echo 終了しました。ウィンドウを閉じるには何かキーを押してください。
pause >nul
