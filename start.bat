@echo off
chcp 65001 > nul
title AI Assistant 起動

echo ========================================
echo    AI Assistant 起動スクリプト
echo ========================================
echo.

REM 仮想環境の存在確認
if not exist "venv" (
    echo エラー: 仮想環境が見つかりません
    echo セットアップスクリプトを先に実行してください:
    echo   setup.bat
    pause
    exit /b 1
)

REM 仮想環境をアクティベート
echo 仮想環境をアクティベート中...
call venv\Scripts\activate.bat

REM アプリケーション起動
echo アプリケーションを起動します...
echo.
python chat.py

REM 終了処理
echo.
echo アプリケーションが終了しました
pause
