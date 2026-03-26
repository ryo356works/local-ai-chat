@echo off
chcp 65001 > nul
title AI Assistant セットアップ

echo ========================================
echo    AI Assistant セットアップ
echo ========================================
echo.

REM Pythonバージョン確認
echo [1/5] Pythonバージョンを確認中...
python --version >nul 2>&1
if errorlevel 1 (
    echo エラー: Pythonがインストールされていません
    echo https://www.python.org/ からPythonをインストールしてください
    pause
    exit /b 1
)
python --version
echo.

REM 仮想環境の作成
echo [2/5] 仮想環境を作成中...
if exist "venv" (
    echo 既存の仮想環境が見つかりました。スキップします。
) else (
    python -m venv venv
    echo ✓ 仮想環境を作成しました
)
echo.

REM 仮想環境のアクティベート
echo [3/5] 仮想環境をアクティベート中...
call venv\Scripts\activate.bat
echo ✓ 仮想環境をアクティベートしました
echo.

REM pipのアップグレード
echo [4/5] pipをアップグレード中...
python -m pip install --upgrade pip -q
echo ✓ pipをアップグレードしました
echo.

REM 依存関係のインストール
echo [5/5] 依存関係をインストール中...
echo これには数分かかる場合があります...
pip install -r requirements.txt
echo ✓ 依存関係をインストールしました
echo.

REM GPU対応の確認（オプション）
echo GPU対応について:
echo GPU（NVIDIA）を使用する場合は、追加の設定が必要です。
echo 詳細はREADME.mdを参照してください。
echo.

REM 完了メッセージ
echo ========================================
echo    セットアップが完了しました！
echo ========================================
echo.
pause
