"""
تثبيت وتسجيل النظام:
  python voice_bridge/setup.py            -> تثبيت المكتبات + إنشاء .env + فحص cloudflared والنموذج
  python voice_bridge/setup.py --install  -> + تسجيل خادم MCP عاماً + إضافة هوكس Stop/Notification + قاعدة CLAUDE.md العامة
"""
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ar/ar_JO/kareem/medium/"
MARK = "voice-call (auto)"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def step(t: str) -> None:
    print(f"\n== {t}")


def main() -> int:
    step("تثبيت المكتبات")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", str(HERE / "requirements.txt")])

    step("نموذج الصوت العربي")
    (HERE / "models").mkdir(exist_ok=True)
    for name in ("ar_JO-kareem-medium.onnx", "ar_JO-kareem-medium.onnx.json"):
        dst = HERE / "models" / name
        if dst.exists() and dst.stat().st_size > 1000:
            print("موجود:", name)
        else:
            print("تنزيل:", name)
            urllib.request.urlretrieve(MODEL_URL + name, dst)

    step(".env")
    env, example = HERE / ".env", HERE / ".env.example"
    if not env.exists():
        shutil.copy(example, env)
        print("أُنشئ voice_bridge/.env — املأ مفاتيح Twilio فيه.")
    else:
        print(".env موجود.")

    step("cloudflared")
    if shutil.which("cloudflared"):
        print("موجود ✅")
    else:
        print("غير مثبت ❌ — ثبّته ثم أعد فتح الطرفية:")
        print("   ويندوز:  winget install Cloudflare.cloudflared")
        print("   ماك:     brew install cloudflared")

    if "--install" not in sys.argv:
        print("\nلتسجيل الأداة والهوكس عاماً: python voice_bridge/setup.py --install")
        return 0

    py = Path(sys.executable).as_posix()
    server = (HERE / "server.py").as_posix()
    hook = (HERE / "hook_call.py").as_posix()

    step("تسجيل خادم MCP")
    claude = shutil.which("claude")
    cmd = [claude or "claude", "mcp", "add", "--scope", "user", "voice-call", "--", py, server]
    if claude:
        r = subprocess.run(cmd)
        print("تم ✅" if r.returncode == 0 else "فشل/مسجّل مسبقاً (تحقق بـ: claude mcp list)")
    else:
        print("أمر claude غير موجود في PATH. نفّذ يدوياً:\n  " + " ".join(f'"{c}"' if " " in c else c for c in cmd))

    step("هوكس Stop و Notification")
    settings = Path.home() / ".claude" / "settings.json"
    settings.parent.mkdir(exist_ok=True)
    data = json.loads(settings.read_text("utf-8")) if settings.exists() else {}
    if settings.exists():
        shutil.copy(settings, settings.with_suffix(".json.bak"))
    hooks = data.setdefault("hooks", {})
    for event, arg in (("Stop", "stop"), ("Notification", "notification")):
        entries = hooks.setdefault(event, [])
        if any("hook_call.py" in h.get("command", "") for e in entries for h in e.get("hooks", [])):
            print(event, "مضاف مسبقاً")
            continue
        entries.append({"hooks": [{"type": "command", "command": f'"{py}" "{hook}" {arg}'}]})
        print(event, "أُضيف ✅")
    settings.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")

    step("قاعدة CLAUDE.md العامة")
    md = Path.home() / ".claude" / "CLAUDE.md"
    old = md.read_text("utf-8") if md.exists() else ""
    if MARK in old:
        print("مضافة مسبقاً")
    else:
        rule = (HERE / "CLAUDE_RULE.md").read_text("utf-8")
        md.write_text(old.rstrip() + f"\n\n<!-- {MARK} -->\n" + rule, "utf-8")
        print("أُضيفت ✅")

    step("مهارة phone-call-user")
    src = HERE / "skill" / "phone-call-user" / "SKILL.md"
    dst = Path.home() / ".claude" / "skills" / "phone-call-user" / "SKILL.md"
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
        print("نُسخت ✅", dst)

    print("\nانتهى. أعد تشغيل Claude Code ليلتقط الأداة والهوكس.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
