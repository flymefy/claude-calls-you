"""
سكربت الهوكس: python hook_call.py stop|notification
يعود فوراً (لا يعطّل Claude) ويطلق عملية خلفية تجري مكالمة إعلامية قصيرة، مع فترة تهدئة لحماية الرصيد.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MESSAGES = {
    "stop": "انتهى Claude من العمل. افتح التطبيق لمراجعة النتيجة.",
    "notification": "Claude يحتاج موافقتك أو انتباهك الآن. افتح التطبيق.",
}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "stop"

    if mode == "worker":  # العملية الخلفية
        import bridge

        bridge.notify(sys.argv[2], wait_for_reply=False)
        return 0

    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    if data.get("stop_hook_active"):
        return 0

    import bridge

    if bridge.env("VOICE_HOOKS", "on").lower() == "off" or bridge.active_problems():
        return 0
    state = bridge.load_state()
    key = f"hook_{mode}"
    now = time.time()
    if now - state.get(key, 0) < int(bridge.env("HOOK_COOLDOWN_SEC", "600")):
        return 0
    state[key] = now
    bridge.save_state(state)

    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "worker", MESSAGES.get(mode, MESSAGES["stop"])], **kwargs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
