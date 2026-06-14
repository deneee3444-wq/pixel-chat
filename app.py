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

_sessions = {}


# ===================== HELPERS =====================
def get_sid():
    return request.cookies.get('pb_sid')

def get_sess():
    sid = get_sid()
    return _sessions.get(sid) if sid else None

def new_sess(sid):
    _sessions[sid] = {
        'token': None, 'user_id': None,
        'api_conv_id': None,          # aktif Supabase conversation ID
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
    """
    if not history:
        return None

    lines = [
        "[ÖNCEKİ KONUŞMA - sadece bağlam içindir, buna doğrudan cevap verme. "
        "Kullanıcının asıl mesajı bu bloğun ALTINDADIR.]"
    ]
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

        prefix = "Kullanıcı" if role == 'user' else "Asistan"
        lines.append(f"{prefix}: {text}")

    lines.append("[ÖNCEKİ KONUŞMA SONU]")
    lines.append("")
    lines.append("Kullanıcının asıl/yeni mesajı:")
    return "\n".join(lines)

def make_local_conv_id():
    return 'conv_' + uuid.uuid4().hex[:12]

def save_conv_to_history(sess):
    """Aktif konuşmayı geçmiş listesine kaydet / güncelle."""
    history = sess.get('history', [])
    if not history:
        return
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

    convs = sess.setdefault('conversations', [])
    local_id  = sess.get('active_local_conv_id')
    api_id    = sess.get('api_conv_id')

    if local_id:
        for c in convs:
            if c.get('conv_id') == local_id:
                c['title']      = title
                c['history']    = history[:]
                c['api_conv_id'] = api_id
                return
        convs.insert(0, {'conv_id': local_id, 'api_conv_id': api_id,
                          'title': title, 'history': history[:]})
    else:
        new_id = make_local_conv_id()
        sess['active_local_conv_id'] = new_id
        convs.insert(0, {'conv_id': new_id, 'api_conv_id': api_id,
                          'title': title, 'history': history[:]})

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
            if res.status_code == 402 or "INSUFFICIENT_CREDITS" in res.text:
                yield f"data: {json.dumps({'type': 'error', 'code': 'INSUFFICIENT_CREDITS'})}\n\n"
                return
            if res.status_code != 200:
                yield f"data: {json.dumps({'type': 'error', 'code': f'HTTP_{res.status_code}'})}\n\n"
                return

            for raw_line in res.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
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

        yield f"data: {json.dumps({'type': 'done', 'full_response': full_response})}\n\n"

    except Exception as e:
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
    return jsonify({'models': AVAILABLE_MODELS})


@app.route('/api/status')
def api_status():
    sess = get_sess()
    if not sess or not sess.get('token'):
        return jsonify({'initialized': False})
    return jsonify({
        'initialized': True,
        'email': sess.get('email', ''),
        'model': sess.get('model', ''),
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
    old_sess = get_sess()
    model = old_sess.get('model', AVAILABLE_MODELS[0]) if old_sess else AVAILABLE_MODELS[0]

    sess = new_sess(sid)
    sess['model'] = model

    email, password = register()
    if not email:
        return jsonify({'success': False, 'error': 'Hesap oluşturulamadı.'}), 500

    token, user_id = do_login(email, password)
    if not token:
        return jsonify({'success': False, 'error': 'Giriş başarısız.'}), 500

    api_conv_id = create_conversation(token, user_id, model)
    if not api_conv_id:
        return jsonify({'success': False, 'error': 'Konuşma başlatılamadı.'}), 500

    sess.update({'token': token, 'user_id': user_id, 'api_conv_id': api_conv_id,
                 'email': email, 'password': password})
    sess['own_api_conv_ids'].add(api_conv_id)

    resp = jsonify({'success': True, 'email': email, 'model': model})
    resp.set_cookie('pb_sid', sid, max_age=86400 * 30, samesite='Lax')
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

    # Eski/başka hesaba ait konuşmadan devam ediliyorsa, o geçmiş bu yeni
    # api_conv_id'de mevcut değildir. Bu yüzden bağlamı API'ye giden mesajın
    # içine gömüyoruz; ekranda kullanıcıya yalnızca kendi yazdığı mesaj görünür.
    pending_context = sess.pop('pending_context', None)
    if pending_context:
        api_message = f"{pending_context}\n{message}"
    else:
        api_message = message

    is_new_conv = not sess.get('active_local_conv_id')

    def generate():
        full_response = ""
        local_conv_id = sess.get('active_local_conv_id')

        if is_new_conv:
            local_conv_id = make_local_conv_id()
            sess['active_local_conv_id'] = local_conv_id
            yield f"data: {json.dumps({'type': 'conv_id', 'conv_id': local_conv_id})}\n\n"

        for event in stream_message(token, api_conv_id, api_message, model, [], attachments):
            yield event
            if event.startswith("data: "):
                try:
                    d = json.loads(event[6:])
                    if d.get('type') == 'chunk':
                        full_response += d.get('content', '')
                    elif d.get('type') == 'done':
                        fr = d.get('full_response', full_response)
                        user_content = (
                            [{"type": "image_url", "image_url": {"url": a["url"]}} for a in attachments]
                            + [{"type": "text", "text": message}]
                        ) if attachments else message
                        sess['history'].append({"role": "user", "content": user_content})
                        sess['history'].append({"role": "assistant", "content": fr})
                        save_conv_to_history(sess)
                    elif d.get('type') == 'billing':
                        sess['total_credits'] += d.get('credits', 0)
                        sess['total_cost'] += d.get('cost', 0.0)
                except Exception:
                    pass

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


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
    if not sess or not sess.get('token'):
        return jsonify({'error': 'Oturum yok'}), 401
    data = request.json or {}
    model = data.get('model', '')
    if model not in AVAILABLE_MODELS:
        return jsonify({'error': 'Geçersiz model'}), 400

    sess['model'] = model
    api_conv_id = create_conversation(sess['token'], sess['user_id'], model)
    if api_conv_id:
        sess['api_conv_id'] = api_conv_id
        sess['own_api_conv_ids'].add(api_conv_id)
        sess['history'] = []
        sess['active_local_conv_id'] = None

    return jsonify({'success': True, 'model': model})


@app.route('/api/clear', methods=['POST'])
def api_clear():
    sess = get_sess()
    if not sess or not sess.get('token'):
        return jsonify({'error': 'Oturum yok'}), 401
    save_conv_to_history(sess)
    sess['history'] = []
    sess['active_local_conv_id'] = None
    api_conv_id = create_conversation(sess['token'], sess['user_id'], sess['model'])
    if api_conv_id:
        sess['api_conv_id'] = api_conv_id
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

    Bu hesapta zaten kendine ait bir api_conv_id'si olan konuşma
    (api_conv_id own_api_conv_ids içinde):
        → o api_conv_id'ye dön, history'yi yükle. Model zaten biliyor,
          ekstra bağlam göndermeye gerek yok.

    Bu hesapta hiç kullanılmamış konuşma (başka/eski hesaba ait
    veya api_conv_id yok):
        → bu konuşmaya ÖZEL, taze bir Supabase conversation_id aç.
          Böylece farklı local konuşmalar aynı conversation_id'yi
          paylaşıp birbirine karışmaz. history'yi sess['history']'e
          yükle (ekranda görünür) ve 'pending_context' olarak işaretle —
          bir sonraki /api/send bu bağlamı yeni mesajın içine gömüp
          gönderir, ekranda ise sadece kullanıcının yazdığı mesaj görünür.
    """
    convs = sess.get('conversations', [])
    for c in convs:
        if c.get('conv_id') == conv_id:
            save_conv_to_history(sess)

            stored_api_id   = c.get('api_conv_id')
            own_ids         = sess.get('own_api_conv_ids', set())
            history         = c['history'][:]

            if stored_api_id and stored_api_id in own_ids:
                # Bu konuşma için bu hesapta zaten ayrılmış bir conversation var
                sess['api_conv_id']     = stored_api_id
                sess['pending_context'] = None
            else:
                # Bu konuşma bu hesapta hiç kullanılmadı — kendine özel taze
                # bir conversation aç ki diğer konuşmalarla karışmasın
                new_api_id = create_conversation(sess['token'], sess['user_id'], sess['model'])
                if new_api_id:
                    sess['own_api_conv_ids'].add(new_api_id)
                    sess['api_conv_id'] = new_api_id
                    c['api_conv_id']    = new_api_id
                else:
                    # Beklenmedik hata — mevcut conversation'ı kullanmaya devam et
                    c['api_conv_id'] = sess['api_conv_id']
                sess['pending_context'] = format_history_context(history)

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


if __name__ == '__main__':
    print("PixelBunny AI Web Interface başlatılıyor...")
    print("http://localhost:5000 adresine gidin")
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
