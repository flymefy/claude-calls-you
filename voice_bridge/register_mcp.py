"""يسجّل أداة call_user في إعدادات Claude Code (نطاق المستخدم) دون الحاجة لأمر `claude` في PATH.

التشغيل:  python voice_bridge\\register_mcp.py
ثم أعد تشغيل Claude Code بالكامل.
"""
import json
import shutil
import sys
import time
from pathlib import Path

cfg = Path.home() / ".claude.json"
server = Path(__file__).resolve().parent / "server.py"

data = {}
if cfg.exists():
    shutil.copy2(cfg, cfg.with_name(f".claude.json.bak-{int(time.time())}"))
    data = json.loads(cfg.read_text(encoding="utf-8") or "{}")

servers = data.setdefault("mcpServers", {})
servers["voice-call"] = {"type": "stdio", "command": sys.executable, "args": [str(server)], "env": {}}
cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("تم تسجيل voice-call في", cfg)
print("الأمر:", sys.executable, server)
print("أعد تشغيل Claude Code الآن، ثم اكتب له: استخدم call_user للاتصال بي واسألني عن المهمة التالية.")
