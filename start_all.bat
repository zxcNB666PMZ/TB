@echo off
chcp 65001 >nul
title Finance AI Launcher
cd /d E:\TB

if not exist "E:\TB\bot_server.py" (
    echo [ERROR] E:\TB\bot_server.py not found. Check the path.
    pause
    exit /b 1
)

echo [1/3] Starting MCP server (port 8000) ...
start "1-MCP-8000" cmd /k "chcp 65001 >nul && cd /d E:\TB && python mcp_server.py"
timeout /t 3 >nul

echo [2/3] Starting Streamlit (port 8501) ...
start "2-Web-8501" cmd /k "chcp 65001 >nul && cd /d E:\TB && python -m streamlit run app.py"
timeout /t 3 >nul

echo [3/3] Starting Feishu bot (long connection) ...
start "3-FeishuBot" cmd /k "chcp 65001 >nul && cd /d E:\TB && python bot_server.py"

echo.
echo ============================================
echo  All three services started.
echo  DO NOT close those windows.
echo    1-MCP-8000   = tool server for AI
echo    2-Web-8501   = web UI  http://localhost:8501
echo    3-FeishuBot  = Feishu robot
echo ============================================
echo.
pause
