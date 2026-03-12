@echo off
chcp 65001 > nul
title RuView Scan - Launcher

echo ========================================
echo   RuView Scan v1.0 - Launcher
echo ========================================
echo.
echo   1. シミュレーションモード (NIC不要・Windows対応)
echo   2. 実運用モード (FeitCSI + AX210・Linux専用)
echo   3. 実運用モード - セットアップスキップ
echo   4. シナリオテスト (シミュレーション + 自動注入)
echo   0. 終了
echo.
set /p choice="選択してください (0-4): "

if "%choice%"=="1" (
    echo.
    echo [INFO] シミュレーションモードで起動します...
    echo [INFO] ブラウザで http://127.0.0.1:8080 を開いてください
    echo.
    python src/main.py --simulate
    goto :end
)

if "%choice%"=="2" (
    echo.
    echo [INFO] 実運用モードで起動します (root権限が必要です)
    echo [WARN] このモードは Linux + AX210 NIC が必要です
    echo.
    python src/main.py
    goto :end
)

if "%choice%"=="3" (
    echo.
    echo [INFO] 実運用モード (セットアップスキップ) で起動します...
    echo.
    python src/main.py --skip-setup
    goto :end
)

if "%choice%"=="4" (
    echo.
    echo --- シナリオ選択 ---
    echo.

    setlocal enabledelayedexpansion
    set idx=0
    for %%f in (tests\scenarios\*.yaml) do (
        set /a idx+=1
        set "file_!idx!=%%f"
        echo   !idx!. %%~nf
    )

    if !idx!==0 (
        echo [ERROR] tests\scenarios\ にYAMLファイルが見つかりません
        goto :end
    )

    echo.
    set /p schoice="シナリオ番号を選択: "
    set "selected=!file_%schoice%!"

    if "!selected!"=="" (
        echo [ERROR] 無効な選択です
        goto :end
    )

    echo.
    echo [INFO] シミュレーションモードで起動します...
    echo [INFO] 起動完了後、シナリオを自動注入します...
    echo.

    start "RuView Scan Server" cmd /c "chcp 65001 > nul && python src/main.py --simulate"

    echo [INFO] サーバー起動待ち (10秒)...
    timeout /t 10 /nobreak > nul

    echo [INFO] シナリオ注入: !selected!
    python tests/inject_scenario.py --scenario "!selected!"

    echo.
    echo [INFO] ブラウザで http://127.0.0.1:8080 を開いてください
    endlocal
    goto :end
)

if "%choice%"=="0" (
    echo 終了します。
    goto :end
)

echo [ERROR] 無効な選択です。

:end
echo.
pause