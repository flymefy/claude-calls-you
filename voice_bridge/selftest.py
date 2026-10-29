"""اختبارات على مراحل:  python selftest.py check | tts "نص" | tunnel | call --yes"""
import sys
import time
import wave

import requests

import bridge

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        print("المفقود في .env:", bridge.config_problems() or "لا شيء ✅")
        print("نموذج الصوت:", "موجود ✅" if bridge.MODEL_PATH.exists() else "مفقود ❌")
        print("cloudflared:", bridge.env("CLOUDFLARED_PATH") or bridge.find_cloudflared() or "غير مثبت ❌")
        print("الوضع:", bridge.mode(), "| ElevenLabs المفقود:", bridge.eleven_problems() or "لا شيء ✅")
    elif cmd == "tts":
        text = bridge.clean_text(sys.argv[2] if len(sys.argv) > 2 else "مرحباً. هذا اختبار الصوت العربي المحلي.")
        out = bridge.AUDIO_DIR / "test.wav"
        t = time.time()
        bridge.synth(text, out)
        with wave.open(str(out)) as w:
            print(f"تم: {out}  المدة {w.getnframes() / w.getframerate():.1f}ث  التوليد {time.time() - t:.1f}ث")
    elif cmd == "tunnel":
        base = bridge.INFRA.ensure()
        bridge.synth("اختبار", bridge.AUDIO_DIR / ("0" * 32 + ".wav"))
        r = requests.get(f"{base}/audio/{'0' * 32}.wav", timeout=15)
        print(base, "->", r.status_code, r.headers.get("content-type"), len(r.content), "bytes")
        (bridge.AUDIO_DIR / ("0" * 32 + ".wav")).unlink(missing_ok=True)
    elif cmd == "eleven-setup":
        print(bridge.eleven_setup())
    elif cmd == "eleven-call":
        if "--yes" not in sys.argv:
            print("هذا سيجري مكالمة حقيقية. أعد التشغيل مع --yes")
            return 1
        print("سيتصل الوكيل بك. تكلّم معه ثم قل موافق أو رفض أو أعطه تعليمات...")
        print(bridge.place_eleven("هذا اختبار. هل أتابع العمل على المشروع؟", True, 240))
    elif cmd == "call":
        if "--yes" not in sys.argv:
            print("هذا سيجري مكالمة حقيقية. أعد التشغيل مع --yes")
            return 1
        print(bridge.notify("أنهيت إعداد نظام الاتصال الصوتي وجرّبته بنجاح. أحتاج منك الآن أن تخبرني بالمهمة التالية التي تريد أن أنفذها.", True, 120))
    return 0


if __name__ == "__main__":
    sys.exit(main())
