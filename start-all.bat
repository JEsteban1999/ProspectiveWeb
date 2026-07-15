@echo off
rem PROSPECTIVE Web — arranca backend (FastAPI :8000) y frontend (Vite :5173)
rem en dos ventanas separadas. Cierra cada ventana para detener su servidor.

start "PROSPECTIVE backend :8000" cmd /k "cd /d %~dp0backend && .venv\Scripts\uvicorn main:app --reload --host 127.0.0.1 --port 8000"
start "PROSPECTIVE frontend :5173" cmd /k "cd /d %~dp0frontend && npm run dev"

echo Backend  -> http://127.0.0.1:8000/docs
echo Frontend -> http://localhost:5173
