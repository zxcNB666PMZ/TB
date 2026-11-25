@echo off
chcp 65001 >nul
ssh root@8.140.220.172 "bash /opt/finance-ai/status.sh"
pause
