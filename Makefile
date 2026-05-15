# PROSPECTIVE Web — development commands
# Usage: make dev:backend | make dev:frontend | make dev:all

BACKEND_DIR = backend
FRONTEND_DIR = frontend
VENV        = $(BACKEND_DIR)\.venv\Scripts

.PHONY: dev\:backend dev\:frontend install\:backend install\:frontend

dev\:backend:
	cd $(BACKEND_DIR) && $(VENV)\uvicorn main:app --reload --host 127.0.0.1 --port 8000

dev\:frontend:
	cd $(FRONTEND_DIR) && npm run dev

install\:backend:
	cd $(BACKEND_DIR) && python -m venv .venv && $(VENV)\pip install -r requirements.txt

install\:frontend:
	cd $(FRONTEND_DIR) && npm install

openapi\:export:
	curl -s http://127.0.0.1:8000/openapi.json -o openapi.json
	@echo openapi.json actualizado
