#!/bin/zsh
# Staging UAT: DB + kho tài liệu RIÊNG trong scratchpad. Không đụng backend/phms.db.
S=/private/tmp/claude-501/-Users-linhpham-Documents-phms/b31585b3-466f-4421-9023-356036bdd04e/scratchpad/uat
mkdir -p $S/storage
export PHMS_DB_URL="sqlite:///$S/uat.db"
export PHMS_DOC_DIR="$S/storage"
export PHMS_SCHEDULER=0
echo "UAT DB = $PHMS_DB_URL"
cd /Users/linhpham/Documents/phms/backend
.venv/bin/python -m app.seed
.venv/bin/python -m app.demo
exec .venv/bin/uvicorn app.main:app --port 8765
