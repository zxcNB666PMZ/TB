@echo off
chcp 65001 >nul
title Stop Finance AI
echo Stopping services ...
taskkill /FI "WINDOWTITLE eq 1-MCP-8000" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq 2-Web-8501" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq 3-FeishuBot" /T /F >nul 2>&1
echo All services stopped.
timeout /t 2 >nul
