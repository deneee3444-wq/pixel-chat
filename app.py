#!/usr/bin/env python3
"""PixelBunny AI - Flask Web Interface"""

import json
import os
import random
import re
import requests
import string
import time
import uuid
from flask import Flask, render_template, request, jsonify, Response, make_response

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ===================== CONSTANTS =====================
API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVzbmRocGFzb3hyd3p4cHpqbGZnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzNDgxNjgsImV4cCI6MjA4NzkyNDE2OH0.cStXgyUmRDoaIctjoH4aNL2DUjjcnZLn_7VFNyEbdzE"
BASE_URL = "https://esndhpasoxrwzxpzjlfg.supabase.co"
DEFAULT_PASSWORD = "SifreniYaz123!"
APP_PASSWORD = "123"

AVAILABLE_MODELS = [
    "claude-opus-4.7", "claude-sonnet-4.6",
    "deepseek-v3.2", "deepseek-v4-flash", "deepseek-v4-pro",
    "gemini-3.1-flash-lite-preview", "gemini-3.1-pro-preview",
    "glm-5.1", "gpt-5.2", "gpt-5.4-nano", "gpt-5.4-mini",
    "gpt-5.4", "gpt-5.5", "grok-4.3", "grok-4.20",
    "kimi-k2", "kimi-k2.6", "minimax-m2.5-pro",
    "qwen3-vl-235b", "qwen3.5-35b-a3b", "qwen3.6-plus"
]

# Modellerin arayüzde gösterilecek isimleri (örn. "Claude Opus 4.7", "GPT 5.2")
MODEL_LABELS = {
    "claude-opus-4.7": "Claude Opus 4.7",
    "claude-sonnet-4.6": "Claude Sonnet 4.6",
    "deepseek-v3.2": "DeepSeek V3.2",
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
    "gemini-3.1-flash-lite-preview": "Gemini 3.1 Flash Lite",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro",
    "glm-5.1": "GLM 5.1",
    "gpt-5.2": "GPT 5.2",
    "gpt-5.4-nano": "GPT 5.4 Nano",
    "gpt-5.4-mini": "GPT 5.4 Mini",
    "gpt-5.4": "GPT 5.4",
    "gpt-5.5": "GPT 5.5",
    "grok-4.3": "Grok 4.3",
    "grok-4.20": "Grok 4.20",
    "kimi-k2": "Kimi K2",
    "kimi-k2.6": "Kimi K2.6",
    "minimax-m2.5-pro": "MiniMax M2.5 Pro",
    "qwen3-vl-235b": "Qwen3 VL 235B",
    "qwen3.5-35b-a3b": "Qwen3.5 35B A3B",
    "qwen3.6-plus": "Qwen3.6 Plus",
}

_sessions = {}


# ===================== HELPERS =====================
def get_sid():
    return request.cookies.get('pb_sid')

def get_sess():
    sid = get_sid()
    return _sessions.get(sid) if sid else None

def new_sess(sid):
    _sessions[sid] = {
        'app_unlocked': False,        # uygulama şifresi girildi mi
        'token': None, 'user_id': None,
        'api_conv_id': None,          # aktif Supabase conversation ID
        'primary_api_conv_id': None,  # bu hesapla birlikte oluşturulan "ana" conversation
        'scratch_api_conv_id': None,  # yabancı konuşmaları sürdürmek için paylaşılan tek conversation
        'own_api_conv_ids': set(),    # bu hesaba ait tüm api_conv_id'ler
        'model': AVAILABLE_MODELS[0],
        'history': [],                # aktif konuşmanın history'si
        'email': None, 'password': DEFAULT_PASSWORD,
        'upload_cache': {}, 'total_credits': 0,
        'total_cost': 0.0,
        'conversations': [],          # [{'conv_id', 'api_conv_id'|None, 'title', 'history'}]
        'active_local_conv_id': None,
        'pending_context': None,      # eski konuşmadan taşınan bağlam (bir sonraki mesaja gömülecek)
    }
    return _sessions[sid]


def format_history_context(history):
    """
    Eski/başka hesaba ait konuşma geçmişini, modele gönderilecek mesajın
    içine gömülecek bir bağlam metnine çevirir. Kullanıcıya ekranda
    gösterilmez — sadece API'ye giden mesajın başına eklenir.
    JSON formatında gönderilir.
    """
    if not history:
        return None

    turns = []
    for turn in history:
        role = turn.get('role')
        content = turn.get('content')
        text = ''
        has_img = False
        if isinstance(content, list):
            text = next((i.get('text', '') for i in content if i.get('type') == 'text'), '')
            has_img = any(i.get('type') == 'image_url' for i in content)
        else:
            text = content or ''

        if has_img and text:
            text = f"{text} [+ görsel ekli]"
        elif has_img:
            text = "[görsel gönderildi]"

        turns.append({"role": role, "content": text})

    context_obj = {
        "type": "conversation_history",
        "note": (
            "Bu konuşmanın TEK GEÇERLİ geçmişi aşağıdaki 'turns' dizisidir. "
            "Buna doğrudan cevap verme, sadece bağlam olarak kullan. "
            "Bu conversation_id üzerinde bununla İLGİSİZ başka konular/geçmişler görüyorsan "
            "onları TAMAMEN YOK SAY ve unutmuş gibi davran. "
            "Kullanıcının asıl mesajı bu JSON bloğunun ALTINDADIR."
        ),
        "turns": turns
    }

    header = json.dumps(context_obj, ensure_ascii=False)
    return f"{header}\n\nKullanıcının asıl/yeni mesajı:"

def make_local_conv_id():
    return 'conv_' + uuid.uuid4().hex[:12]

def save_conv_to_history(sess):
    """Aktif konuşmayı geçmiş listesine kaydet / güncelle."""
    history = sess.get('history', [])
    if not history:
        return

    def derive_title():
        title = "Konuşma"
        for turn in history:
            if turn['role'] == 'user':
                content = turn['content']
                if isinstance(content, list):
                    title = next((i['text'] for i in content if i.get('type') == 'text'), 'Konuşma')
                else:
                    title = str(content)
                title = (title[:48] + '…') if len(title) > 48 else title
                break
        return title

    convs = sess.setdefault('conversations', [])
    local_id  = sess.get('active_local_conv_id')
    api_id    = sess.get('api_conv_id')

    if local_id:
        for c in convs:
            if c.get('conv_id') == local_id:
                if not c.get('title_locked'):
                    c['title'] = derive_title()
                c['history']    = history[:]
                c['api_conv_id'] = api_id
                return
        convs.insert(0, {'conv_id': local_id, 'api_conv_id': api_id,
                          'title': derive_title(), 'history': history[:]})
    else:
        new_id = make_local_conv_id()
        sess['active_local_conv_id'] = new_id
        convs.insert(0, {'conv_id': new_id, 'api_conv_id': api_id,
                          'title': derive_title(), 'history': history[:]})

    sess['conversations'] = convs[:30]


# ===================== TEMP EMAIL =====================
class eTemp:
    def random_email(self, length=15):
        return ''.join(
            random.SystemRandom().choice(string.ascii_lowercase + string.digits)
            for _ in range(length)
        ) + '@spamok.com'

    def getConfirmLink(self, mail, timeout=30):
        address = mail.replace('@spamok.com', '')
        for _ in range(timeout):
            try:
                r = requests.get(f'https://api.spamok.com/v2/EmailBox/{address}', timeout=10)
                for m in r.json().get('mails', []):
                    if 'Confirm' in m.get('subject', '') or 'Pixel Bunny' in m.get('fromDisplay', ''):
                        er = requests.get(f'https://api.spamok.com/v2/Email/{address}/{m["id"]}', timeout=10)
                        html = er.json().get('messageHtml', '')
                        match = re.search(
                            r'href="(https://mt-link\.pixelbunny\.ai/cl/[^\"]+)"[^>]*background-color:#7c3aed', html
                        )
                        if match:
                            return match.group(1)
                        links = re.findall(r'href="(https://mt-link\.pixelbunny\.ai/cl/[^\"]+)"', html)
                        return links[1] if len(links) >= 2 else (links[0] if links else None)
            except Exception:
                pass
            time.sleep(1)
        return None


# ===================== ACCOUNT =====================
def register():
    temp = eTemp()
    email = temp.random_email()
    headers = {
        "apikey": API_KEY, "authorization": f"Bearer {API_KEY}",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://pixelbunny.ai", "referer": "https://pixelbunny.ai/",
        "x-client-info": "supabase-js-web/2.98.0",
        "x-supabase-api-version": "2024-01-01",
    }
    payload = {
        "email": email, "password": DEFAULT_PASSWORD, "data": {},
        "gotrue_meta_security": {}, "code_challenge": None, "code_challenge_method": None,
    }
    r = requests.post(f"{BASE_URL}/auth/v1/signup?redirect_to=https://pixelbunny.ai",
                      headers=headers, json=payload, timeout=15)
    if r.status_code not in [200, 201]:
        return None, None
    link = temp.getConfirmLink(email)
    if not link:
        return None, None
    requests.get(link, allow_redirects=True, timeout=15)
    return email, DEFAULT_PASSWORD


def do_login(email, password):
    r = requests.post(
        f"{BASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": API_KEY, "content-type": "application/json;charset=UTF-8"},
        json={"email": email, "password": password}, timeout=15
    )
    if r.status_code != 200:
        return None, None
    d = r.json()
    return d.get("access_token"), d.get("user", {}).get("id")


def create_conversation(token, user_id, model_id):
    r = requests.post(
        f"{BASE_URL}/rest/v1/chat_conversations?select=id",
        headers={
            "apikey": API_KEY, "authorization": f"Bearer {token}",
            "content-type": "application/json", "content-profile": "public",
            "prefer": "return=representation", "origin": "https://pixelbunny.ai",
            "referer": "https://pixelbunny.ai/", "x-client-info": "supabase-js-web/2.98.0",
            "accept": "application/vnd.pgrst.object+json",
        },
        json={"user_id": user_id, "default_model_id": model_id}, timeout=15
    )
    return r.json().get("id") if r.status_code == 201 else None


# ===================== CHAT STREAM =====================
def stream_message(token, api_conv_id, message, model_id, history=None, attachments=None):
    """
    history: konuşma bağlamı — Supabase bu parametreyi alıp modele geçiriyor.
    Yeni hesapta bile history göndererek eski konuşma bağlamı korunur.
    """
    if history is None: history = []
    if attachments is None: attachments = []

    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json", "accept": "*/*",
        "origin": "https://pixelbunny.ai", "referer": "https://pixelbunny.ai/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    payload = {
        "conversation_id": api_conv_id,
        "model_id": model_id,
        "message": message,
        "attachments": attachments,
        "incognito": False,
        "history": history,   # bağlam — yeni hesapta da çalışır
    }

    full_response = ""
    try:
        with requests.post(
            f"{BASE_URL}/functions/v1/chat-completion",
            headers=headers, json=payload, stream=True, timeout=120
        ) as res:
            res.encoding = "utf-8"
            if res.status_code == 423:
                yield f"data: {json.dumps({'type': 'error', 'code': 'LOCKED'})}\n\n"
                return
            if res.status_code == 402:
                yield f"data: {json.dumps({'type': 'error', 'code': 'INSUFFICIENT_CREDITS'})}\n\n"
                return
            if res.status_code != 200:
                yield f"data: {json.dumps({'type': 'error', 'code': f'HTTP_{res.status_code}'})}\n\n"
                return

            done_received = False
            for raw_line in res.iter_lines(decode_unicode=True, chunk_size=1):
                if raw_line is None:
                    continue
                line = raw_line.strip()
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    done_received = True
                    break
                if "INSUFFICIENT_CREDITS" in data_str:
                    yield f"data: {json.dumps({'type': 'error', 'code': 'INSUFFICIENT_CREDITS'})}\n\n"
                    return
                try:
                    data = json.loads(data_str)
                    if data.get("type") == "billing":
                        yield f"data: {json.dumps({'type': 'billing', 'credits': data.get('credits_charged', 0), 'cost': data.get('cost_usd', 0)})}\n\n"
                        continue
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("delta", {}).get("content", "")
                        if content:
                            full_response += content
                            yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"
                except json.JSONDecodeError:
                    pass

        if done_received and full_response:
            yield f"data: {json.dumps({'type': 'done', 'full_response': full_response})}\n\n"
        elif full_response:
            # [DONE] gelmeden akış bitti — kesilme
            yield f"data: {json.dumps({'type': 'stream_interrupted', 'full_response': full_response})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'stream_interrupted', 'full_response': ''})}\n\n"

    except Exception as e:
        if full_response:
            yield f"data: {json.dumps({'type': 'stream_interrupted', 'full_response': full_response})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'code': str(e)})}\n\n"


# ===================== ROUTES =====================
@app.route('/')
def index():
    resp = make_response(render_template('index.html'))
    if not request.cookies.get('pb_sid'):
        sid = str(uuid.uuid4())
        resp.set_cookie('pb_sid', sid, max_age=86400 * 30, samesite='Lax')
    return resp


@app.route('/api/models')
def api_models():
    return jsonify({'models': [
        {'id': m, 'label': MODEL_LABELS.get(m, m)} for m in AVAILABLE_MODELS
    ]})


@app.route('/api/status')
def api_status():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'initialized': False})
    return jsonify({
        'initialized': True,
        'account_created': bool(sess.get('token')),
        'email': sess.get('email', ''),
        'model': sess.get('model', AVAILABLE_MODELS[0]),
        'message_count': len(sess.get('history', [])) // 2,
        'total_credits': sess.get('total_credits', 0),
        'total_cost': round(sess.get('total_cost', 0.0), 5),
    })


@app.route('/api/init', methods=['POST'])
def api_init():
    data = request.json or {}
    if data.get('password') != APP_PASSWORD:
        return jsonify({'success': False, 'error': 'Hatalı şifre.'}), 401

    sid = get_sid() or str(uuid.uuid4())
    sess = new_sess(sid)
    sess['app_unlocked'] = True

    resp = jsonify({'success': True, 'account_created': False, 'model': sess['model']})
    resp.set_cookie('pb_sid', sid, max_age=86400 * 30, samesite='Lax')
    return resp


@app.route('/api/logout', methods=['POST'])
def api_logout():
    sid = get_sid()
    if sid and sid in _sessions:
        del _sessions[sid]
    resp = jsonify({'success': True})
    resp.set_cookie('pb_sid', '', expires=0)
    return resp


@app.route('/api/send', methods=['POST'])
def api_send():
    sess = get_sess()
    if not sess or not sess.get('token'):
        return jsonify({'error': 'Oturum bulunamadı.'}), 401

    data        = request.json or {}
    message     = data.get('message', '').strip()
    attachments = data.get('attachments', [])

    if not message:
        return jsonify({'error': 'Mesaj boş.'}), 400

    token       = sess['token']
    api_conv_id = sess['api_conv_id']
    model       = sess['model']

    is_scratch = (
        api_conv_id == sess.get('scratch_api_conv_id')
        and api_conv_id != sess.get('primary_api_conv_id')
    )

    if is_scratch:
        # Paylaşılan "scratch" conversation — bu conversation_id birden fazla
        # yabancı local konuşma tarafından kullanılıyor. Bu yüzden bu konuşmanın
        # TAM geçmişini HER mesajda yeniden gömüyoruz; ekranda kullanıcıya
        # yalnızca kendi yazdığı mesaj görünür.
        ctx = format_history_context(sess.get('history', []))
        api_message = f"{ctx}\n{message}" if ctx else message
    else:
        # Ana (primary) conversation — server kendi geçmişini hatırlıyor.
        # Eğer hesap sıfırlanırken bir konuşma buraya taşındıysa (carry),
        # bu geçmiş bir kerelik bağlam olarak gömülür.
        pending_context = sess.pop('pending_context', None)
        if pending_context:
            api_message = f"{pending_context}\n{message}"
        else:
            api_message = message

    # Yeni konuşmayı generate() içinde değil, burada (request başında) oluştur.
    # Böylece istemci ne kadar hızlı iptal ederse etsin conv_id atanmış ve
    # kullanıcı mesajı kaydedilmiş olur.
    is_new_conv = not sess.get('active_local_conv_id')
    if is_new_conv:
        new_local_conv_id = make_local_conv_id()
        sess['active_local_conv_id'] = new_local_conv_id
    else:
        new_local_conv_id = None

    # Kullanıcı mesajını hemen geçmişe ekle (AI yanıtı için placeholder).
    # Bu sayede stream iptal edilse de mesaj kaybolmaz.
    user_content = (
        [{"type": "image_url", "image_url": {"url": a["url"]}} for a in attachments]
        + [{"type": "text", "text": message}]
    ) if attachments else message
    sess['history'].append({"role": "user", "content": user_content})
    sess['history'].append({"role": "assistant", "content": ""})  # placeholder
    save_conv_to_history(sess)
    # history'deki son AI mesajının index'ini tut (sonradan güncellenecek)
    ai_turn_index = len(sess['history']) - 1

    def generate():
        full_response = ""
        history_saved = False

        if new_local_conv_id:
            yield f"data: {json.dumps({'type': 'conv_id', 'conv_id': new_local_conv_id})}\n\n"

        try:
            for event in stream_message(token, api_conv_id, api_message, model, [], attachments):
                yield event
                if event.startswith("data: "):
                    try:
                        d = json.loads(event[6:])
                        if d.get('type') == 'chunk':
                            full_response += d.get('content', '')
                        elif d.get('type') == 'done':
                            fr = d.get('full_response', full_response)
                            # Placeholder'ı gerçek yanıtla güncelle
                            if ai_turn_index < len(sess['history']):
                                sess['history'][ai_turn_index] = {"role": "assistant", "content": fr}
                            save_conv_to_history(sess)
                            history_saved = True
                        elif d.get('type') == 'billing':
                            sess['total_credits'] += d.get('credits', 0)
                            sess['total_cost'] += d.get('cost', 0.0)
                    except Exception:
                        pass
        except GeneratorExit:
            pass
        finally:
            if not history_saved:
                # Stream tamamlanmadan kesildi — placeholder'ı mevcut yanıtla güncelle
                if ai_turn_index < len(sess['history']):
                    sess['history'][ai_turn_index] = {"role": "assistant", "content": full_response}
                save_conv_to_history(sess)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
                              'Connection': 'close'})


@app.route('/api/upload', methods=['POST'])
def api_upload():
    sess = get_sess()
    if not sess or not sess.get('token'):
        return jsonify({'error': 'Oturum yok'}), 401
    if 'file' not in request.files:
        return jsonify({'error': 'Dosya eksik'}), 400

    file = request.files['file']
    token = sess['token']
    headers = {
        "authorization": f"Bearer {token}", "origin": "https://pixelbunny.ai",
        "referer": "https://pixelbunny.ai/", "accept": "*/*", "user-agent": "Mozilla/5.0",
    }
    files = {"file": (file.filename, file.read(), file.content_type or "image/jpeg")}
    r = requests.post(f"{BASE_URL}/functions/v1/upload-input", headers=headers,
                      files=files, timeout=30)
    if r.status_code == 200:
        url = r.json().get("url")
        sess.setdefault('upload_cache', {})[url or str(uuid.uuid4())] = {
            'url': url, 'conv_id': request.form.get('conv_id'), 'filename': file.filename
        }
        return jsonify({'url': url, 'type': 'image/png', 'name': file.filename})
    return jsonify({'error': f'Yükleme başarısız ({r.status_code})'}), 500


@app.route('/api/new_chat', methods=['POST'])
def api_new_chat():
    """423 Locked geldiğinde: mevcut hesapta yeni bir konuşma başlat.
    carry_history=True ile çağrıldığında geçmiş taşınır ve yeni conv_id döner."""
    sess = get_sess()
    if not sess or not sess.get('token'):
        return jsonify({'error': 'Oturum yok'}), 401

    data          = request.json or {}
    carry         = data.get('carry_history', False)
    carry_conv_id = data.get('conv_id')

    # Taşınacak geçmişi bul (reset ile aynı mantık)
    carry_history  = []
    carry_local_id = None
    if carry:
        if carry_conv_id:
            for c in sess.get('conversations', []):
                if c.get('conv_id') == carry_conv_id:
                    carry_history  = c['history'][:]
                    carry_local_id = carry_conv_id
                    break
        if not carry_history:
            carry_history  = sess.get('history', [])
            carry_local_id = sess.get('active_local_conv_id')

    save_conv_to_history(sess)
    sess['history'] = []
    sess['active_local_conv_id'] = None
    sess['pending_context'] = None

    api_conv_id = create_conversation(sess['token'], sess['user_id'], sess['model'])
    if not api_conv_id:
        return jsonify({'success': False, 'error': 'Konuşma başlatılamadı.'}), 500

    sess['api_conv_id']         = api_conv_id
    sess['primary_api_conv_id'] = api_conv_id
    sess['own_api_conv_ids'].add(api_conv_id)

    new_conv_id = None
    if carry_history:
        # Geçmişi session'a yükle; bir sonraki mesaja bağlam olarak gömülecek
        sess['history']              = carry_history
        sess['active_local_conv_id'] = carry_local_id
        sess['pending_context']      = format_history_context(carry_history)
        new_conv_id                  = carry_local_id
        # conversations listesindeki api_conv_id'yi güncelle
        for c in sess.get('conversations', []):
            if c.get('conv_id') == carry_local_id:
                c['api_conv_id'] = api_conv_id
                break

    return jsonify({'success': True, 'new_conv_id': new_conv_id, 'carried': bool(carry_history)})


@app.route('/api/reset', methods=['POST'])
def api_reset():
    data          = request.json or {}
    carry         = data.get('carry_history', False)
    carry_conv_id = data.get('conv_id')

    sid      = get_sid() or str(uuid.uuid4())
    old_sess = get_sess()
    model    = old_sess.get('model', AVAILABLE_MODELS[0]) if old_sess else AVAILABLE_MODELS[0]

    # Taşınacak geçmişi ve local_id'yi bul
    carry_history  = []
    carry_local_id = None
    if carry and old_sess:
        if carry_conv_id:
            for c in old_sess.get('conversations', []):
                if c.get('conv_id') == carry_conv_id:
                    carry_history  = c['history'][:]
                    carry_local_id = carry_conv_id
                    break
        if not carry_history:
            carry_history  = old_sess.get('history', [])
            carry_local_id = old_sess.get('active_local_conv_id')

    if old_sess:
        save_conv_to_history(old_sess)
    old_conversations = old_sess.get('conversations', []) if old_sess else []

    sess = new_sess(sid)
    sess['app_unlocked']  = True
    sess['model']         = model
    sess['conversations'] = old_conversations   # tüm geçmiş taşınsın

    email, password = register()
    if not email:
        return jsonify({'success': False, 'error': 'Hesap oluşturulamadı.'}), 500

    token, user_id = do_login(email, password)
    if not token:
        return jsonify({'success': False, 'error': 'Giriş başarısız.'}), 500

    # Yeni hesap için taze bir conversation aç
    api_conv_id = create_conversation(token, user_id, model)
    if not api_conv_id:
        return jsonify({'success': False, 'error': 'Konuşma başlatılamadı.'}), 500

    sess.update({'token': token, 'user_id': user_id, 'api_conv_id': api_conv_id,
                 'primary_api_conv_id': api_conv_id,
                 'email': email, 'password': password})
    sess['own_api_conv_ids'].add(api_conv_id)

    new_conv_id = None
    if carry_history:
        # Geçmişi session'a yükle (ekranda görünür); ayrıca bir sonraki
        # mesaja gömülecek bağlam olarak işaretle — model yeni hesapta
        # bu geçmişi bilmediği için.
        sess['history']              = carry_history
        sess['active_local_conv_id'] = carry_local_id
        sess['pending_context']      = format_history_context(carry_history)
        new_conv_id                  = carry_local_id
        # conversations listesindeki kaydın api_conv_id'sini güncelle
        for c in sess['conversations']:
            if c.get('conv_id') == carry_local_id:
                c['api_conv_id'] = api_conv_id
                break

    resp_data = {
        'success': True, 'email': email, 'model': model,
        'carried': bool(carry_history), 'new_conv_id': new_conv_id,
    }
    resp = jsonify(resp_data)
    resp.set_cookie('pb_sid', sid, max_age=86400 * 30, samesite='Lax')
    return resp


@app.route('/api/model', methods=['POST'])
def api_model():
    sess = get_sess()
    if not sess:
        return jsonify({'error': 'Oturum yok'}), 401
    data = request.json or {}
    model = data.get('model', '')
    if model not in AVAILABLE_MODELS:
        return jsonify({'error': 'Geçersiz model'}), 400

    sess['model'] = model

    if not sess.get('token'):
        # Henüz hesap oluşturulmadı — tercih kaydedildi, hesap açılınca uygulanır
        return jsonify({'success': True, 'model': model})

    if sess.get('active_local_conv_id'):
        # Kullanıcı şu anda bir konuşmanın içinde — o konuşmadan çıkma.
        # Yeni model bundan sonraki mesajlarda kullanılır (model_id her
        # mesajda ayrıca gönderiliyor), conversation_id ve geçmiş aynen kalır.
        return jsonify({'success': True, 'model': model})

    api_conv_id = create_conversation(sess['token'], sess['user_id'], model)
    if api_conv_id:
        sess['api_conv_id']         = api_conv_id
        sess['primary_api_conv_id'] = api_conv_id
        sess['own_api_conv_ids'].add(api_conv_id)
        sess['history'] = []
        sess['active_local_conv_id'] = None
        sess['pending_context'] = None

    return jsonify({'success': True, 'model': model})


@app.route('/api/clear', methods=['POST'])
def api_clear():
    sess = get_sess()
    if not sess or not sess.get('token'):
        return jsonify({'error': 'Oturum yok'}), 401
    save_conv_to_history(sess)
    sess['history'] = []
    sess['active_local_conv_id'] = None
    sess['pending_context'] = None
    api_conv_id = create_conversation(sess['token'], sess['user_id'], sess['model'])
    if api_conv_id:
        sess['api_conv_id']         = api_conv_id
        sess['primary_api_conv_id'] = api_conv_id
        sess['own_api_conv_ids'].add(api_conv_id)
    return jsonify({'success': True})


@app.route('/api/history')
def api_history():
    sess = get_sess()
    if not sess:
        return jsonify({'history': []})
    simplified = []
    for turn in sess.get('history', []):
        role    = turn['role']
        content = turn['content']
        if isinstance(content, list):
            text   = next((i['text'] for i in content if i.get('type') == 'text'), '')
            images = [i['image_url']['url'] for i in content if i.get('type') == 'image_url']
            simplified.append({'role': role, 'text': text, 'images': images})
        else:
            simplified.append({'role': role, 'text': content, 'images': []})
    return jsonify({'history': simplified})


@app.route('/api/conversations')
def api_conversations():
    sess = get_sess()
    if not sess:
        return jsonify({'conversations': []})
    convs = sess.get('conversations', [])
    result = [
        {
            'idx':     i,
            'conv_id': c.get('conv_id', str(i)),
            'title':   c['title'],
            'count':   len(c['history']) // 2,
        }
        for i, c in enumerate(convs)
    ]
    return jsonify({'conversations': result})


def _switch_to_conv(sess, conv_id):
    """
    Verilen local conv_id'ye geç.

    - Bu konuşma bu hesabın PRIMARY conversation'ına aitse (yani bu hesapla
      başlatılmış/devam ettirilmiş konuşma):
        → primary api_conv_id'ye dön. Server zaten geçmişi biliyor,
          ekstra bağlam göndermeye gerek yok.

    - Bu konuşma bu hesapta hiç kullanılmamışsa (başka/eski hesaba ait):
        → hesap için PAYLAŞILAN bir "scratch" conversation kullanılır
          (yoksa bir kerelik oluşturulur — hesap başına en fazla 1 ekstra
          conversation, böylece hesabın conversation kotası tükenmez).
          history'yi sess['history']'e yükle (ekranda görünür); /api/send
          bu konuşmanın TAM geçmişini her mesajda yeniden gömerek gönderir,
          böylece farklı yabancı konuşmalar scratch'i paylaşsa da birbirine
          karışmaz.
    """
    convs = sess.get('conversations', [])
    for c in convs:
        if c.get('conv_id') == conv_id:
            save_conv_to_history(sess)

            stored_api_id = c.get('api_conv_id')
            primary       = sess.get('primary_api_conv_id')
            history       = c['history'][:]

            if stored_api_id == primary and primary:
                # Bu hesabın ana konuşması — server zaten hatırlıyor
                sess['api_conv_id']     = primary
                sess['pending_context'] = None
            else:
                # Yabancı konuşma — hesap için paylaşılan scratch'i kullan
                scratch = sess.get('scratch_api_conv_id')
                if not scratch:
                    scratch = create_conversation(sess['token'], sess['user_id'], sess['model'])
                    if scratch:
                        sess['scratch_api_conv_id'] = scratch
                        sess['own_api_conv_ids'].add(scratch)

                if scratch:
                    sess['api_conv_id'] = scratch
                    c['api_conv_id']    = scratch
                # scratch oluşturulamadıysa mevcut api_conv_id ile devam edilir
                sess['pending_context'] = None

            sess['history']              = history
            sess['active_local_conv_id'] = conv_id
            return True, conv_id, len(history) // 2

    return False, None, 0


@app.route('/api/conversation/load', methods=['POST'])
def api_conversation_load():
    sess = get_sess()
    if not sess or not sess.get('token'):
        return jsonify({'error': 'Oturum yok'}), 401

    data    = request.json or {}
    conv_id = data.get('conv_id')
    idx     = data.get('idx')

    convs = sess.get('conversations', [])

    if not conv_id and idx is not None:
        try:
            i = int(idx)
            if 0 <= i < len(convs):
                conv_id = convs[i].get('conv_id', str(i))
        except (ValueError, TypeError):
            pass

    if not conv_id:
        return jsonify({'error': 'Konuşma bulunamadı'}), 404

    ok, cid, msg_count = _switch_to_conv(sess, conv_id)
    if ok:
        return jsonify({'success': True, 'conv_id': cid, 'message_count': msg_count})
    return jsonify({'error': 'Konuşma bulunamadı'}), 404


@app.route('/api/conversation/delete', methods=['POST'])
def api_conversation_delete():
    sess = get_sess()
    if not sess:
        return jsonify({'error': 'Oturum yok'}), 401

    data    = request.json or {}
    conv_id = data.get('conv_id')
    if not conv_id:
        return jsonify({'error': 'Konuşma bulunamadı'}), 404

    convs = sess.get('conversations', [])
    new_convs = [c for c in convs if c.get('conv_id') != conv_id]
    if len(new_convs) == len(convs):
        return jsonify({'error': 'Konuşma bulunamadı'}), 404
    sess['conversations'] = new_convs

    if sess.get('active_local_conv_id') == conv_id:
        sess['history'] = []
        sess['active_local_conv_id'] = None
        sess['pending_context'] = None
        if sess.get('primary_api_conv_id'):
            sess['api_conv_id'] = sess['primary_api_conv_id']

    return jsonify({'success': True})


@app.route('/api/conversation/rename', methods=['POST'])
def api_conversation_rename():
    sess = get_sess()
    if not sess:
        return jsonify({'error': 'Oturum yok'}), 401

    data    = request.json or {}
    conv_id = data.get('conv_id')
    title   = (data.get('title') or '').strip()
    if not conv_id or not title:
        return jsonify({'error': 'Geçersiz istek'}), 400

    title = (title[:48] + '…') if len(title) > 48 else title

    for c in sess.get('conversations', []):
        if c.get('conv_id') == conv_id:
            c['title'] = title
            c['title_locked'] = True
            return jsonify({'success': True, 'title': title})

    return jsonify({'error': 'Konuşma bulunamadı'}), 404


if __name__ == '__main__':
    print("PixelBunny AI Web Interface başlatılıyor...")
    print("http://localhost:5000 adresine gidin")
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
