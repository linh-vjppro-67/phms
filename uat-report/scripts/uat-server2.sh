#!/bin/zsh
# Staging #2 (cổng 8767): break-glass hết hạn sau 1 phút để kiểm BG-02b. DB riêng.
S=/private/tmp/claude-501/-Users-linhpham-Documents-phms/b31585b3-466f-4421-9023-356036bdd04e/scratchpad/uat2
mkdir -p $S/storage
export PHMS_DB_URL="sqlite:///$S/uat2.db" PHMS_DOC_DIR="$S/storage" PHMS_SCHEDULER=0 PHMS_BREAK_GLASS_MINUTES=1
cd /Users/linhpham/Documents/phms/backend
.venv/bin/python -m app.seed && .venv/bin/python -m app.demo
exec .venv/bin/uvicorn app.main:app --port 8767
