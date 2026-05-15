@echo off
REM Arrancar el backend de PROSPECTIVE Web en modo desarrollo
REM Doble clic o ejecutar desde PowerShell

cd /d "%~dp0"
.venv\Scripts\uvicorn main:app --reload --host 127.0.0.1 --port 8000

pause
