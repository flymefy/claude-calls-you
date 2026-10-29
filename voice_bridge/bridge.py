"""
voice_bridge/bridge.py
Piper (صوت عربي محلي) + Flask (webhook) + cloudflared (نفق مجاني) + Twilio (المكالمة) + ElevenLabs Agents (وكيل صوتي اختياري).
ملاحظة: لا نطبع شيئاً إلى stdout لأن خادم MCP يستخدمه للبروتوكول؛ كل السجلات إلى stderr أو calls.log.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

AUDIO_DIR = HERE / "output"
AUDIO_DIR.mkdir(exist_ok=True)
MODEL_PATH = HERE / "models" / "ar_JO-kareem-medium.onnx"
CALLS_LOG = HERE / "calls.log"
STATE_FILE = HERE / "state.json"
MAX_PLAYS = 4

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("twilio.http_client").setLevel(logging.WARNING)
log = logging.getLogger("voice_bridge")

SPEECH = lambda: env("VOICE_REPLY", "speech").lower() == "speech"  # noqa: E731
PROMPT_SUFFIX_DIGITS = " للموافقة اضغط واحد. للرفض اضغط اثنين. للإعادة اضغط ثلاثة. وللكتابة لي في التطبيق اضغط أربعة."
PROMPT_SUFFIX_SPEECH = " تكلم الآن: قل موافق، أو ارفض، أو أعطني الأمر الذي تريد أن أنفذه."
APPROVE_WORDS = ("موافق", "اوافق", "أوافق", "نعم", "تمام", "نفذ", "نفّذ", "اكمل", "أكمل", "تابع", "اجل", "أجل", "طيب", "حسنا", "حسناً")
REJECT_WORDS = ("ارفض", "أرفض", "رفض", "لا", "توقف", "الغ", "ألغ", "لا تنفذ", "لا تنفّذ")
DIGIT_AUDIO = {
    "1": ("ok", "تم تسجيل موافقتك.", "approved"),
    "2": ("no", "تم تسجيل رفضك.", "rejected"),
    "4": ("app", "حسناً، اكتب تعليماتك في تطبيق Claude Code.", "will_reply_in_app"),
}


# ----------------------------------------------------------------- أدوات عامة
def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def mask(num: str) -> str:
    return num[:3] + "***" + num[-2:] if len(num) > 6 else "***"


def audit(event: str, **kw) -> None:
    """سجل بدون أسرار: لا مفاتيح ولا أرقام كاملة."""
    try:
        line = json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **kw}, ensure_ascii=False)
        with CALLS_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text("utf-8"))
    except Exception:
        return {}


def save_state(s: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(s), "utf-8")
    except OSError:
        pass


def rate_limited() -> bool:
    s = load_state()
    now = time.time()
    recent = [t for t in s.get("calls", []) if now - t < 3600]
    return len(recent) >= int(env("MAX_CALLS_PER_HOUR", "6"))


def record_call() -> None:
    s = load_state()
    now = time.time()
    s["calls"] = [t for t in s.get("calls", []) if now - t < 3600] + [now]
    save_state(s)


def config_problems() -> list[str]:
    p = [k for k in ("TWILIO_ACCOUNT_SID", "TWILIO_FROM_NUMBER", "MY_PHONE_NUMBER") if not env(k)]
    if not (env("TWILIO_AUTH_TOKEN") or (env("TWILIO_API_KEY") and env("TWILIO_API_SECRET"))):
        p.append("TWILIO_AUTH_TOKEN (أو TWILIO_API_KEY + TWILIO_API_SECRET)")
    return p


def twilio_client():
    from twilio.rest import Client

    if env("TWILIO_API_KEY") and env("TWILIO_API_SECRET"):
        return Client(env("TWILIO_API_KEY"), env("TWILIO_API_SECRET"), env("TWILIO_ACCOUNT_SID"))
    return Client(env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN"))


def clean_text(t: str) -> str:
    limit = int(env("MAX_MESSAGE_CHARS", "350"))
    t = re.sub(r"```.*?```", " ", t or "", flags=re.S)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[`*_#>|]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + "."
    return t


# ----------------------------------------------------------------- Piper
_voice = None
_voice_lock = threading.Lock()


def _synth_eleven(text: str, path: Path) -> None:
    """صوت ElevenLabs العربي داخل مكالمة Twilio. يُخزَّن الناتج مؤقتاً لتوفير الحصة المجانية."""
    import hashlib
    import requests

    key = env("ELEVENLABS_API_KEY")
    voice = env("ELEVENLABS_VOICE_ID", "xvhpbk8otnNHtT3fjCpr")
    model = env("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
    cache_dir = AUDIO_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / (hashlib.sha1(f"{voice}|{model}|{text}".encode("utf-8")).hexdigest() + ".wav")
    if not cached.exists():
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
            params={"output_format": "pcm_16000"},
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={"text": text, "model_id": model, "language_code": "ar",
                  "voice_settings": {"stability": 0.55, "similarity_boost": 0.8, "speed": 0.95}},
            timeout=40,
        )
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs TTS HTTP {r.status_code}: {r.text[:200]}")
        with wave.open(str(cached), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(r.content)
    path.write_bytes(cached.read_bytes())


def synth(text: str, path: Path) -> None:
    if env("TTS_ENGINE", "piper").lower() == "elevenlabs" and env("ELEVENLABS_API_KEY"):
        try:
            _synth_eleven(text, path)
            return
        except Exception as e:  # ارجع إلى Piper المحلي دائماً حتى لا تفشل المكالمة
            audit("tts_eleven_failed", error=str(e)[:200])
    _synth_piper(text, path)


def _synth_piper(text: str, path: Path) -> None:
    global _voice
    with _voice_lock:
        if _voice is None:
            if not MODEL_PATH.exists():
                raise RuntimeError(f"نموذج الصوت غير موجود: {MODEL_PATH}")
            from piper import PiperVoice

            _voice = PiperVoice.load(str(MODEL_PATH))
        with wave.open(str(path), "wb") as w:
            if hasattr(_voice, "synthesize_wav"):
                _voice.synthesize_wav(text, w)  # piper-tts >= 1.3
            else:
                _voice.synthesize(text, w)  # الإصدارات الأقدم


def cleanup_old_audio(max_age: int = 3600) -> None:
    now = time.time()
    for p in AUDIO_DIR.glob("*.wav"):
        try:
            if now - p.stat().st_mtime > max_age and p.name != "test.wav":
                p.unlink()
        except OSError:
            pass


# ----------------------------------------------------------------- Flask + النفق
from flask import Flask, Response, abort, request, send_file  # noqa: E402
from twilio.twiml.voice_response import Gather, VoiceResponse  # noqa: E402

app = Flask(__name__)
CALLS: dict[str, dict] = {}


def find_cloudflared() -> str | None:
    exe = shutil.which("cloudflared")
    if exe:
        return exe
    roots = [os.environ.get(k, "") for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    cands = [Path(r) / "cloudflared" / "cloudflared.exe" for r in roots if r]
    cands += [Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe"]
    cands += [Path("/usr/local/bin/cloudflared"), Path("/opt/homebrew/bin/cloudflared")]
    for c in cands:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            pass
    return None


class _Infra:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.server = None
        self.port = 0
        self.proc: subprocess.Popen | None = None
        self.base = ""

    def ensure(self) -> str:
        with self.lock:
            if self.server is None:
                from werkzeug.serving import make_server

                self.server = make_server("127.0.0.1", int(env("LOCAL_PORT", "0")), app, threaded=True)
                self.port = self.server.server_port
                threading.Thread(target=self.server.serve_forever, daemon=True).start()
                log.info("webhook محلي على المنفذ %s", self.port)
            if env("PUBLIC_BASE_URL"):
                self.base = env("PUBLIC_BASE_URL").rstrip("/")
                return self.base
            if self.proc is None or self.proc.poll() is not None:
                self._start_tunnel()
            return self.base

    def _start_tunnel(self) -> None:
        exe = env("CLOUDFLARED_PATH") or find_cloudflared()
        if not exe:
            raise RuntimeError("cloudflared غير مثبت. ثبّته: winget install Cloudflare.cloudflared (ويندوز) أو brew install cloudflared")
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(
            [exe, "tunnel", "--url", f"http://127.0.0.1:{self.port}", "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", creationflags=flags,
        )
        holder: dict[str, str] = {}
        found = threading.Event()
        proc = self.proc

        def pump() -> None:
            for line in proc.stdout:  # type: ignore[union-attr]
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m and m.group(0) != "https://api.trycloudflare.com" and "url" not in holder:
                    holder["url"] = m.group(0)
                    found.set()

        threading.Thread(target=pump, daemon=True).start()
        if not found.wait(45):
            proc.terminate()
            raise RuntimeError("تعذّر الحصول على رابط النفق من cloudflared")
        self.base = holder["url"]
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if requests.get(self.base + "/health", timeout=4).text == "ok":
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        log.info("النفق جاهز")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


INFRA = _Infra()
atexit.register(INFRA.stop)


def _xml(vr: VoiceResponse) -> Response:
    return Response(str(vr), mimetype="text/xml")


def _guard(token: str) -> dict:
    c = CALLS.get(token)
    if c is None:
        audit("webhook_unknown_token", route=request.path.split("/")[1])
        abort(404)
    audit("webhook_hit", route=request.path.split("/")[1], digits=request.form.get("Digits", ""), cs=request.form.get("CallStatus", ""))
    auth = env("TWILIO_AUTH_TOKEN")
    if auth:  # التحقق من توقيع Twilio (الرابط العشوائي هو الحماية الأساسية)
        from twilio.request_validator import RequestValidator

        url = INFRA.base + request.full_path.rstrip("?")
        if not RequestValidator(auth).validate(url, request.form, request.headers.get("X-Twilio-Signature", "")):
            audit("webhook_bad_signature", url=url, seen=request.url, proto=request.headers.get("X-Forwarded-Proto", ""),
                  keys=sorted(request.form.keys()), enforced=env("ENFORCE_SIGNATURE") == "1")
            if env("ENFORCE_SIGNATURE") == "1":  # افتراضياً تحذير فقط؛ الحماية الأساسية هي الرابط العشوائي
                abort(403)
    return c


@app.get("/health")
def health():
    return "ok"


@app.get("/audio/<name>")
def audio(name: str):
    if not re.fullmatch(r"[0-9a-f]{32}(_ok|_no|_app|_ins)?\.wav", name):
        abort(404)
    p = AUDIO_DIR / name
    if not p.is_file():
        abort(404)
    c = CALLS.get(name[:32])
    if c:
        c["fetched"].set()
    return send_file(p, mimetype="audio/wav")


@app.route("/twiml/<token>", methods=["GET", "POST"])
def twiml(token: str):
    c = _guard(token)
    if c.get("agent"):
        try:
            r = _el("POST", "/v1/convai/twilio/register-call", json={
                "agent_id": env("ELEVENLABS_AGENT_ID"),
                "from_number": request.form.get("From") or env("TWILIO_FROM_NUMBER"),
                "to_number": request.form.get("To") or env("MY_PHONE_NUMBER"),
                "direction": "outbound",
                "conversation_initiation_client_data": {"dynamic_variables": {"message": c["spoken"]}}})
            if not r.ok:
                raise RuntimeError(_el_err(r))
            audit("agent_registered")
            return Response(r.text, mimetype="text/xml")
        except Exception as e:  # noqa: BLE001
            audit("agent_register_failed", error=str(e)[:200])
            vr = VoiceResponse()
            vr.hangup()
            return _xml(vr)
    attempt = int(request.args.get("attempt", "1"))
    c["plays"] += 1
    base = INFRA.base
    vr = VoiceResponse()
    if c["plays"] > MAX_PLAYS:
        vr.hangup()
        return _xml(vr)
    vr.pause(length=1)
    url = f"{base}/audio/{token}.wav"
    if not c["wait"]:
        vr.play(url)
        vr.pause(length=1)
        vr.hangup()
        return _xml(vr)
    if SPEECH():
        g = Gather(input="dtmf speech", num_digits=1, timeout=8, speech_timeout="auto",
                   language=env("TWILIO_SPEECH_LANG", "ar-SA"), hints="موافق, ارفض, نفذ, توقف",
                   action=f"{base}/gather/{token}", method="POST")
    else:
        g = Gather(input="dtmf", num_digits=1, timeout=8, action=f"{base}/gather/{token}", method="POST")
    g.play(url)
    vr.append(g)
    if attempt < 2:
        vr.redirect(f"{base}/twiml/{token}?attempt={attempt + 1}", method="POST")
    else:
        vr.hangup()
    return _xml(vr)


@app.post("/gather/<token>")
def gather(token: str):
    c = _guard(token)
    digit = request.form.get("Digits", "")
    speech = (request.form.get("SpeechResult") or "").strip()
    vr = VoiceResponse()
    if speech and not digit:
        words = re.sub(r"[^\w\s]", " ", speech).split()
        short = len(words) <= 3
        if short and any(w in REJECT_WORDS for w in words) or (short and speech.startswith("لا")):
            decision = "rejected"
        elif short and any(w in APPROVE_WORDS for w in words):
            decision = "approved"
        else:
            decision = "instructions"
        try:
            conf = float(request.form.get("Confidence") or 1)
        except ValueError:
            conf = 1.0
        audit("speech_heard", chars=len(speech), decision=decision, conf=round(conf, 2))
        if decision != "instructions" and conf < float(env("MIN_SPEECH_CONFIDENCE", "0.5")):
            decision = "instructions"  # قرار حاسم بثقة ضعيفة: اطلب التأكيد بدل افتراضه
        if decision == "instructions":
            c["pending"] = speech[:1000]
            c["retries"] = c.get("retries", 0)
            try:
                synth(f"فهمت أنك قلت: {speech[:200]}. إن كان صحيحاً قل نعم أو اضغط واحد. وإن لم يكن، قل لا أو اضغط اثنين وأعد الأمر.",
                      AUDIO_DIR / f"{token}_ins.wav")
                g = Gather(input="dtmf speech", num_digits=1, timeout=8, speech_timeout="auto",
                           language=env("TWILIO_SPEECH_LANG", "ar-SA"), hints="نعم, لا",
                           action=f"{INFRA.base}/confirm/{token}", method="POST")
                g.play(f"{INFRA.base}/audio/{token}_ins.wav")
                vr.append(g)
            except Exception:  # noqa: BLE001
                vr.hangup()
            return _xml(vr)
        say = "تم تسجيل موافقتك." if decision == "approved" else "تم تسجيل رفضك."
        if not c["result"]:
            c["result"] = decision
        try:
            synth(say, AUDIO_DIR / f"{token}_ins.wav")
            vr.play(f"{INFRA.base}/audio/{token}_ins.wav")
        except Exception:  # noqa: BLE001
            pass
        vr.hangup()
        c["event"].set()
        return _xml(vr)
    if digit in DIGIT_AUDIO:
        suffix, _, result = DIGIT_AUDIO[digit]
        if not c["result"]:
            c["result"] = result
        vr.play(f"{INFRA.base}/audio/{token}_{suffix}.wav")
        vr.hangup()
        c["event"].set()
    else:  # 3 أو أي رقم آخر: أعد الرسالة
        vr.redirect(f"{INFRA.base}/twiml/{token}?attempt=1", method="POST")
    return _xml(vr)


@app.post("/confirm/<token>")
def confirm(token: str):
    c = _guard(token)
    digit = request.form.get("Digits", "")
    speech = (request.form.get("SpeechResult") or "").strip()
    words = re.sub(r"[^\w\s]", " ", speech).split()
    yes = digit == "1" or any(w in APPROVE_WORDS for w in words)
    vr = VoiceResponse()
    if yes and c.get("pending"):
        c["text"] = c["pending"]
        if not c["result"]:
            c["result"] = "instructions"
        audit("instructions_confirmed", chars=len(c["text"]))
        try:
            synth("تم. سأنفذ أمرك الآن.", AUDIO_DIR / f"{token}_ins.wav")
            vr.play(f"{INFRA.base}/audio/{token}_ins.wav")
        except Exception:  # noqa: BLE001
            pass
        vr.hangup()
        c["event"].set()
    elif digit == "2" or speech:  # رفض التأكيد: أعد المحاولة مرتين كحد أقصى
        c["retries"] = c.get("retries", 0) + 1
        if c["retries"] <= 2:
            vr.redirect(f"{INFRA.base}/twiml/{token}?attempt=1", method="POST")
        else:
            vr.hangup()
    else:  # صمت: لا تنفذ شيئاً
        vr.hangup()
    return _xml(vr)


TERMINAL = ("completed", "busy", "no-answer", "failed", "canceled")


def _finish(c: dict, st: str) -> None:
    c["status"] = st
    if st in TERMINAL:
        if not c["result"]:
            if st == "completed":
                c["result"] = "no_reply" if c["wait"] else "delivered"
            elif st == "failed":
                c["result"] = "failed"
            else:
                c["result"] = "no_answer"
        c["done"].set()
        c["event"].set()


@app.post("/status/<token>")
def status(token: str):
    c = _guard(token)
    _finish(c, request.form.get("CallStatus", ""))
    return ("", 204)


# ----------------------------------------------------------------- الدالة الرئيسية
MEANING = {
    "approved": "المستخدم وافق. تابع التنفيذ.",
    "rejected": "المستخدم رفض. لا تنفذ الإجراء.",
    "will_reply_in_app": "المستخدم سيكتب تعليماته في التطبيق. توقف وانتظر رسالته.",
    "delivered": "وصلت الرسالة (مكالمة إعلامية).",
    "instructions": "هذه تعليمات المستخدم الصوتية (حقل text). نفّذها.",
    "no_decision": "انتهت المحادثة دون قرار واضح. لا تنفذ الإجراء الحساس، واكتب السؤال في المحادثة.",
    "no_reply": "المستخدم ردّ لكنه لم يضغط أي رقم. لا تنفذ الإجراء الحساس، واكتب السؤال في المحادثة.",
    "no_answer": "لم يُجب المستخدم. لا تنفذ الإجراء الحساس، واكتب السؤال في المحادثة.",
    "timeout": "انتهت المهلة دون رد. لا تنفذ الإجراء الحساس، واكتب السؤال في المحادثة.",
    "failed": "فشلت المكالمة. لا تنفذ الإجراء الحساس، واكتب السؤال في المحادثة.",
}


def place_call(message: str, wait_for_reply: bool = True, timeout_sec: int = 120) -> dict:
    agent = mode() == "agent"  # وكيل ElevenLabs يتحدث معك عبر مكالمة Twilio (register-call)
    problems = config_problems() + ([k for k in ("ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID") if not env(k)] if agent else [])
    if problems:
        return {"status": "not_configured", "missing": problems}
    msg = clean_text(message)
    if not msg:
        return {"status": "error", "detail": "الرسالة فارغة"}
    if rate_limited():
        audit("rate_limited")
        return {"status": "rate_limited",
                "meaning": "تم بلوغ حد المكالمات في الساعة. اكتب السؤال في المحادثة وانتظر."}

    token = secrets.token_hex(16)
    c = {"token": token, "wait": wait_for_reply, "plays": 0, "result": None, "status": "",
         "event": threading.Event(), "done": threading.Event(), "fetched": threading.Event(), "sid": "",
         "agent": agent, "spoken": (msg if wait_for_reply else msg + " هذا إشعار فقط، لا حاجة للرد."), "t0": time.time()}
    client = None
    try:
        base = INFRA.ensure()
        cleanup_old_audio()
        if not agent:
            synth(msg + ((PROMPT_SUFFIX_SPEECH if SPEECH() else PROMPT_SUFFIX_DIGITS) if wait_for_reply else ""), AUDIO_DIR / f"{token}.wav")
        if wait_for_reply and not agent:
            for suffix, text, _ in DIGIT_AUDIO.values():
                synth(text, AUDIO_DIR / f"{token}_{suffix}.wav")
        CALLS[token] = c
        client = twilio_client()
        call = client.calls.create(
            to=env("MY_PHONE_NUMBER"), from_=env("TWILIO_FROM_NUMBER"),
            url=f"{base}/twiml/{token}",  # الحساب التجريبي يرفض معاملات إضافية (status_callback, timeout)
        )
        c["sid"] = call.sid
        record_call()
        audit("call_started", to=mask(env("MY_PHONE_NUMBER")), wait=wait_for_reply, chars=len(msg), sid=call.sid)
    except Exception as e:  # noqa: BLE001
        log.error("فشل بدء المكالمة: %s", type(e).__name__)
        audit("call_error", error=f"{type(e).__name__}: {str(e)[:200]}")
        return {"status": "failed", "detail": f"{type(e).__name__}: {str(e)[:300]}",
                "meaning": MEANING["failed"]}

    limit = (max(timeout_sec, int(env("AGENT_MIN_WAIT", "300"))) if agent else timeout_sec) if wait_for_reply else 90

    def poll() -> None:
        while not c["event"].is_set():
            try:
                _finish(c, client.calls(c["sid"]).fetch().status)
            except Exception:  # noqa: BLE001
                pass
            c["event"].wait(2)

    threading.Thread(target=poll, daemon=True).start()
    if not c["event"].wait(limit):
        c["result"] = c["result"] or "timeout"
        try:
            st = client.calls(c["sid"]).fetch().status
            client.calls(c["sid"]).update(status="canceled" if st in ("queued", "ringing") else "completed")
        except Exception:  # noqa: BLE001
            pass
    elif c["result"] in ("approved", "rejected", "will_reply_in_app", "instructions"):
        c["done"].wait(15)  # دع رسالة التأكيد تُشغَّل قبل حذف الملفات

    if agent and wait_for_reply and c["status"] == "completed":
        return _agent_result(c)
    result = c["result"] or "failed"
    audit("call_result", result=result, sid=c["sid"])
    threading.Timer(120, lambda: [p.unlink(missing_ok=True) for p in AUDIO_DIR.glob(f"{token}*.wav")]).start()
    out = {"status": result, "meaning": MEANING.get(result, "")}
    if result == "instructions" and c.get("text"):
        out["text"] = c["text"]
    return out


# ----------------------------------------------------------------- وضع ElevenLabs (وكيل صوتي يتحدث معك؛ يمر عبر Twilio)
EL_API = "https://api.elevenlabs.io"


def eleven_problems() -> list[str]:
    return [k for k in ("ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "ELEVENLABS_PHONE_NUMBER_ID", "MY_PHONE_NUMBER") if not env(k)]


def _el(method: str, path: str, **kw) -> requests.Response:
    return requests.request(method, EL_API + path, headers={"xi-api-key": env("ELEVENLABS_API_KEY")}, timeout=30, **kw)


def _el_err(r: requests.Response) -> str:
    try:
        d = r.json().get("detail", r.json())
        return f"HTTP {r.status_code}: {(d.get('message') if isinstance(d, dict) else str(d))[:300]}"
    except Exception:  # noqa: BLE001
        return f"HTTP {r.status_code}"


def set_env_value(key: str, value: str) -> None:
    path = HERE / ".env"
    text = path.read_text("utf-8") if path.exists() else ""
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{key}={value}\n"
    path.write_text(text, "utf-8")
    os.environ[key] = value


def eleven_setup() -> dict:
    """يتحقق من المفتاح، ويستورد رقم Twilio إلى ElevenLabs، ويربطه بالوكيل، ويحفظ المعرّف في .env."""
    for k in ("ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
        if not env(k):
            return {"ok": False, "step": "env", "missing": k}
    r = _el("GET", "/v1/convai/agents", params={"page_size": 1})
    if not r.ok:
        return {"ok": False, "step": "api_key", "detail": _el_err(r)}
    pid = env("ELEVENLABS_PHONE_NUMBER_ID")
    if not pid:
        r = _el("POST", "/v1/convai/phone-numbers", json={
            "provider": "twilio", "phone_number": env("TWILIO_FROM_NUMBER"), "label": "Claude Code",
            "sid": env("TWILIO_ACCOUNT_SID"), "token": env("TWILIO_AUTH_TOKEN")})
        if not r.ok:
            return {"ok": False, "step": "import_number", "detail": _el_err(r)}
        pid = r.json().get("phone_number_id", "")
        set_env_value("ELEVENLABS_PHONE_NUMBER_ID", pid)
    r = _el("PATCH", f"/v1/convai/phone-numbers/{pid}", json={"agent_id": env("ELEVENLABS_AGENT_ID")})
    if not r.ok:
        return {"ok": False, "step": "assign_agent", "detail": _el_err(r)}
    return {"ok": True, "phone_number_id": pid}


def _agent_result(c: dict) -> dict:
    """بعد انتهاء مكالمة Twilio: اقرأ محادثة الوكيل واستخرج القرار/التعليمات."""
    deadline = time.time() + 90
    data: dict = {}
    conv = ""
    while time.time() < deadline:
        try:
            if not conv:
                lst = _el("GET", "/v1/convai/conversations", params={"agent_id": env("ELEVENLABS_AGENT_ID"), "page_size": 5})
                for it in (lst.json().get("conversations") or []) if lst.ok else []:
                    if (it.get("start_time_unix_secs") or 0) >= c["t0"] - 5:
                        conv = it.get("conversation_id", "")
                        break
            if conv:
                d = _el("GET", f"/v1/convai/conversations/{conv}")
                if d.ok:
                    data = d.json()
                    if data.get("status") in ("done", "failed") and (data.get("analysis") or {}).get("data_collection_results") is not None:
                        break
        except requests.RequestException:
            pass
        time.sleep(4)
    if not data:
        audit("agent_result", result="no_reply")
        return {"status": "no_reply", "meaning": MEANING["no_reply"]}
    out = _eleven_parse(data)
    audit("agent_result", result=out["status"], conv=conv)
    return out


def _eleven_parse(data: dict) -> dict:
    results = (data.get("analysis") or {}).get("data_collection_results") or {}
    decision = str((results.get("decision") or {}).get("value") or "").strip().lower()
    instr = str((results.get("instructions") or {}).get("value") or "").strip()
    user_turns = [t.get("message", "") for t in data.get("transcript", []) if t.get("role") == "user" and t.get("message")]
    if decision in ("approved", "rejected"):
        res = decision
    elif decision == "instructions" and instr:
        res = "instructions"
    elif user_turns:
        res = "no_decision"
    else:
        res = "no_reply"
    audit("eleven_result", result=res, turns=len(user_turns))
    out = {"status": res, "meaning": MEANING.get(res, "")}
    if instr and res == "instructions":
        out["text"] = instr[:1000]
    if res == "no_decision":
        out["user_said"] = " | ".join(user_turns)[:500]
    return out


def place_eleven(message: str, wait_for_reply: bool = True, timeout_sec: int = 180) -> dict:
    problems = eleven_problems()
    if problems:
        return {"status": "not_configured", "missing": problems}
    msg = clean_text(message)
    if not msg:
        return {"status": "error", "detail": "الرسالة فارغة"}
    if rate_limited():
        audit("rate_limited")
        return {"status": "rate_limited", "meaning": "تم بلوغ حد المكالمات في الساعة. اكتب السؤال في المحادثة وانتظر."}
    spoken = msg if wait_for_reply else msg + " هذا إشعار فقط، لا حاجة للرد."
    try:
        r = _el("POST", "/v1/convai/twilio/outbound-call", json={
            "agent_id": env("ELEVENLABS_AGENT_ID"), "agent_phone_number_id": env("ELEVENLABS_PHONE_NUMBER_ID"),
            "to_number": env("MY_PHONE_NUMBER"),
            "conversation_initiation_client_data": {"dynamic_variables": {"message": spoken}}})
        body = r.json() if r.content else {}
        if not r.ok or body.get("success") is False:
            raise RuntimeError(_el_err(r) if not r.ok else str(body.get("message", ""))[:300])
        conv = body.get("conversation_id") or ""
        record_call()
        audit("eleven_call_started", to=mask(env("MY_PHONE_NUMBER")), wait=wait_for_reply, conv=conv)
    except Exception as e:  # noqa: BLE001
        audit("eleven_call_error", error=str(e)[:200])
        return {"status": "failed", "detail": str(e)[:300], "meaning": MEANING["failed"]}
    if not wait_for_reply:
        return {"status": "delivered", "meaning": MEANING["delivered"]}

    deadline = time.time() + timeout_sec
    data: dict = {}
    while time.time() < deadline:
        time.sleep(5)
        try:
            d = _el("GET", f"/v1/convai/conversations/{conv}")
            if d.ok:
                data = d.json()
                if data.get("status") in ("done", "failed"):
                    break
        except requests.RequestException:
            pass
    if data.get("status") not in ("done", "failed"):
        audit("eleven_result", result="timeout")
        return {"status": "timeout", "meaning": MEANING["timeout"]}
    return _eleven_parse(data)


# ----------------------------------------------------------------- اختيار الوضع
def mode() -> str:
    return env("NOTIFY_MODE", "twilio").lower()


def active_problems() -> list[str]:
    return eleven_problems() if mode() == "elevenlabs" else config_problems()


def notify(message: str, wait_for_reply: bool = True, timeout_sec: int = 120) -> dict:
    if mode() == "elevenlabs":
        return place_eleven(message, wait_for_reply, max(timeout_sec, 180))
    return place_call(message, wait_for_reply, timeout_sec)
