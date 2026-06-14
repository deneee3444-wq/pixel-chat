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

# In-memory session store  { sid -> {...} }
_sessions = {}


# ===================== HELPERS =====================
def get_sid():
    return request.cookies.get('pb_sid')

def get_sess():
    sid = get_sid()
    return _sessions.get(sid) if sid else None

def new_sess(sid):
    _sessions[sid] = {
        'token': None, 'user_id': None, 'conv_id': None,
        'model': AVAILABLE_MODELS[0], 'history': [],
        'email': None, 'password': DEFAULT_PASSWORD,
        'upload_cache': {}, 'total_credits': 0,
        'total_cost': 0.0, 'carry_history': None,
        'conversations': [],
    }
    return _sessions[sid]

def save_conv_to_history(sess):
    """Mevcut konuşmayı geçmiş listesine kaydet."""
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
    convs.insert(0, {'title': title, 'history': history[:]})
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
def stream_message(token, conv_id, message, model_id, history=None, attachments=None):
    """SSE generator for streaming chat."""
    if history is None: history = []
    if attachments is None: attachments = []

    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json", "accept": "*/*",
        "origin": "https://pixelbunny.ai", "referer": "https://pixelbunny.ai/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    payload = {
        "conversation_id": conv_id, "model_id": model_id,
        "message": message, "attachments": attachments,
        "incognito": False, "history": history,
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


def build_carried_message(carry_history, new_user_input):
    lines = []
    carried_attachments = []
    for turn in carry_history:
        role = turn["role"]
        content = turn["content"]
        if role == "user":
            if isinstance(content, list):
                text_part = ""
                for item in content:
                    if item.get("type") == "text":
                        text_part = item["text"]
                    elif item.get("type") == "image_url":
                        carried_attachments.append({"url": item["image_url"]["url"], "type": "image/png"})
                lines.append(f"user: {text_part}")
            else:
                lines.append(f"user: {content}")
        else:
            lines.append(f"assistant: {content}")
    history_text = "\n".join(lines)
    full_message = f"[Önceki Konuşma]\n{history_text}\n\n[Yeni Mesaj]\n{new_user_input}"
    return full_message, carried_attachments


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

    # Şifre kontrolü
    if data.get('password') != APP_PASSWORD:
        return jsonify({'success': False, 'error': 'Hatalı şifre.'}), 401

    sid = get_sid() or str(uuid.uuid4())
    old_sess = get_sess()
    model = old_sess.get('model', AVAILABLE_MODELS[0]) if old_sess else AVAILABLE_MODELS[0]

    sess = new_sess(sid)
    sess['model'] = model

    email, password = register()
    if not email:
        return jsonify({'success': False, 'error': 'Hesap oluşturulamadı. Lütfen tekrar deneyin.'}), 500

    token, user_id = do_login(email, password)
    if not token:
        return jsonify({'success': False, 'error': 'Giriş başarısız.'}), 500

    conv_id = create_conversation(token, user_id, model)
    if not conv_id:
        return jsonify({'success': False, 'error': 'Konuşma başlatılamadı.'}), 500

    sess.update({'token': token, 'user_id': user_id, 'conv_id': conv_id,
                 'email': email, 'password': password})

    resp = jsonify({'success': True, 'email': email, 'model': model})
    resp.set_cookie('pb_sid', sid, max_age=86400 * 30, samesite='Lax')
    return resp


@app.route('/api/send', methods=['POST'])
def api_send():
    sess = get_sess()
    if not sess or not sess.get('token'):
        return jsonify({'error': 'Oturum bulunamadı. Lütfen yenileyin.'}), 401

    data = request.json or {}
    message = data.get('message', '').strip()
    attachments = data.get('attachments', [])

    if not message:
        return jsonify({'error': 'Mesaj boş.'}), 400

    token = sess['token']
    conv_id = sess['conv_id']
    model = sess['model']
    history = sess.get('history', [])
    carry = sess.pop('carry_history', None)

    if carry:
        final_message, carried_atts = build_carried_message(carry, message)
        final_atts = carried_atts + attachments
    else:
        final_message = message
        final_atts = attachments

    def generate():
        full_response = ""
        for event in stream_message(token, conv_id, final_message, model, history, final_atts):
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
                        history.append({"role": "user", "content": user_content})
                        history.append({"role": "assistant", "content": fr})
                        sess['history'] = history
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
        return jsonify({'url': url, 'type': 'image/png', 'name': file.filename})
    return jsonify({'error': f'Yükleme başarısız ({r.status_code})'}), 500


@app.route('/api/reset', methods=['POST'])
def api_reset():
    data = request.json or {}
    carry = data.get('carry_history', False)

    sid = get_sid() or str(uuid.uuid4())
    old_sess = get_sess()

    # Mevcut modeli koru
    model = old_sess.get('model', AVAILABLE_MODELS[0]) if old_sess else AVAILABLE_MODELS[0]
    carry_history = old_sess.get('history', []) if (carry and old_sess) else []

    # Mevcut konuşmayı geçmişe kaydet
    if old_sess:
        save_conv_to_history(old_sess)
    old_conversations = old_sess.get('conversations', []) if old_sess else []

    sess = new_sess(sid)
    sess['model'] = model
    sess['conversations'] = old_conversations
    if carry_history:
        sess['carry_history'] = carry_history

    email, password = register()
    if not email:
        return jsonify({'success': False, 'error': 'Hesap oluşturulamadı.'}), 500

    token, user_id = do_login(email, password)
    if not token:
        return jsonify({'success': False, 'error': 'Giriş başarısız.'}), 500

    conv_id = create_conversation(token, user_id, model)
    if not conv_id:
        return jsonify({'success': False, 'error': 'Konuşma başlatılamadı.'}), 500

    sess.update({'token': token, 'user_id': user_id, 'conv_id': conv_id,
                 'email': email, 'password': password})

    resp = jsonify({'success': True, 'email': email, 'model': model, 'carried': bool(carry_history)})
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
    conv_id = create_conversation(sess['token'], sess['user_id'], model)
    if conv_id:
        sess['conv_id'] = conv_id
        sess['history'] = []

    return jsonify({'success': True, 'model': model})


@app.route('/api/clear', methods=['POST'])
def api_clear():
    sess = get_sess()
    if not sess or not sess.get('token'):
        return jsonify({'error': 'Oturum yok'}), 401
    save_conv_to_history(sess)
    sess['history'] = []
    conv_id = create_conversation(sess['token'], sess['user_id'], sess['model'])
    if conv_id:
        sess['conv_id'] = conv_id
    return jsonify({'success': True})


@app.route('/api/history')
def api_history():
    sess = get_sess()
    if not sess:
        return jsonify({'history': []})
    simplified = []
    for turn in sess.get('history', []):
        role = turn['role']
        content = turn['content']
        if isinstance(content, list):
            text = next((i['text'] for i in content if i.get('type') == 'text'), '')
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
    result = [{'idx': i, 'title': c['title'], 'count': len(c['history']) // 2}
              for i, c in enumerate(convs)]
    return jsonify({'conversations': result})


@app.route('/api/conversation/load', methods=['POST'])
def api_conversation_load():
    sess = get_sess()
    if not sess or not sess.get('token'):
        return jsonify({'error': 'Oturum yok'}), 401

    save_conv_to_history(sess)

    data = request.json or {}
    idx = data.get('idx', 0)
    convs = sess.get('conversations', [])

    if idx < 0 or idx >= len(convs):
        return jsonify({'error': 'Geçersiz konuşma'}), 400

    conv = convs.pop(idx)
    sess['conversations'] = convs
    sess['history'] = conv['history']

    conv_id = create_conversation(sess['token'], sess['user_id'], sess['model'])
    if conv_id:
        sess['conv_id'] = conv_id

    return jsonify({'success': True, 'message_count': len(conv['history']) // 2})


if __name__ == '__main__':
    print("PixelBunny AI Web Interface başlatılıyor...")
    print("http://localhost:5000 adresine gidin")
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
