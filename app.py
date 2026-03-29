import os, json, uuid, requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

PENDING_FILE = "/data/pending.json"

def load_pending():
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, "r") as f:
            return json.load(f)
    return {}

def save_pending(data):
    with open(PENDING_FILE, "w") as f:
        json.dump(data, f)

app = Flask(__name__)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
INSTAGRAM_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TRENDS = [
    {"keyword": "minimalist gold ring", "style": "minimal", "palette": "warm gold, ivory"},
    {"keyword": "dainty layered necklace", "style": "elegant", "palette": "gold, cream"},
    {"keyword": "thin stacking rings", "style": "minimal", "palette": "gold, marble"},
    {"keyword": "delicate chain bracelet", "style": "fine", "palette": "gold, linen"},
    {"keyword": "simple hoop earrings", "style": "classic", "palette": "gold, white"},
    {"keyword": "pendant necklace minimal", "style": "modern", "palette": "gold, terracotta"},
    {"keyword": "fine jewelry everyday", "style": "luxury", "palette": "warm gold, nude"},
]

def call_claude(prompt):
    r = requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": "claude-sonnet-4-20250514", "max_tokens": 500, "messages": [{"role": "user", "content": prompt}]},
        timeout=60)
    data = r.json()
    if "content" not in data:
        raise Exception(f"Claude error: {data}")
    return data["content"][0]["text"].strip()

def generate_image(prompt):
    r = requests.post("https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={"model": "gpt-image-1", "prompt": prompt, "size": "1024x1024", "quality": "high", "n": 1},
        timeout=120)
    data = r.json()
    if "data" not in data:
        raise Exception(f"OpenAI error: {data}")
    item = data["data"][0]
    if "url" in item:
        return item["url"]
    if "b64_json" in item:
        return "data:image/png;base64," + item["b64_json"]
    raise Exception(f"No image: {data}")

def generate_caption(trend):
    raw = call_claude(f"Write Instagram caption for AiSerena jewelry brand. Theme: {trend['keyword']}. 2-3 sentences English, elegant, 3 emojis, CTA 'Shop the collection, link in bio'. Add 20 hashtags. Return ONLY JSON: {{\"caption\":\"...\",\"hashtags\":\"#... #...\"}}")
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def send_telegram(content_id, image_url, caption, hashtags):
    keyboard = {"inline_keyboard": [[{"text": "✅ Approve", "callback_data": f"approve:{content_id}"}, {"text": "❌ Reject", "callback_data": f"reject:{content_id}"}]]}
    text = f"New AiSerena post ready!\n\n{caption}\n\n{hashtags}"
    if image_url.startswith("data:"):
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "reply_markup": keyboard})
    else:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
            json={"chat_id": TELEGRAM_CHAT_ID, "photo": image_url, "caption": text, "reply_markup": keyboard})
    return r.json()

def publish_instagram(image_url, caption, hashtags):
    full = f"{caption}\n\n{hashtags}"
    r1 = requests.post(f"https://graph.facebook.com/v19.0/{INSTAGRAM_ACCOUNT_ID}/media",
        params={"image_url": image_url, "caption": full, "access_token": INSTAGRAM_TOKEN})
    print(f"Instagram media yanıtı: {r1.status_code} - {r1.text}")
    if not r1.text:
        return {"error": "Instagram boş yanıt döndürdü"}
    cid = r1.json().get("id")
    if not cid:
        return {"error": r1.json()}
    r2 = requests.post(f"https://graph.facebook.com/v19.0/{INSTAGRAM_ACCOUNT_ID}/media_publish",
        params={"creation_id": cid, "access_token": INSTAGRAM_TOKEN})
    print(f"Instagram publish yanıtı: {r2.status_code} - {r2.text}")
    return r2.json()

@app.route("/generate", methods=["POST"])
def generate():
    from datetime import date
    trend = TRENDS[date.today().weekday() % len(TRENDS)]
    content_id = str(uuid.uuid4())[:8]
    try:
        image_prompt = call_claude(f"Write gpt-image-1 prompt for luxury minimalist jewelry photo. Theme:{trend['keyword']}. Style:{trend['style']}. Colors:{trend['palette']}. Rules: product photography, clean white marble background, natural light, no hands, no people. Under 80 words, return only the prompt.")
        image_url = generate_image(image_prompt)
        content = generate_caption(trend)
        pending = load_pending()
        pending[content_id] = {"image_url": image_url, "caption": content["caption"], "hashtags": content["hashtags"]}
        save_pending(pending)
        tg = send_telegram(content_id, image_url, content["caption"], content["hashtags"])
        return jsonify({"status": "sent_for_approval", "content_id": content_id, "telegram": tg})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    callback = data.get("callback_query", {})
    cb_data = callback.get("data", "")
    if ":" not in cb_data:
        return jsonify({"ok": True})
    action, content_id = cb_data.split(":", 1)
    pending = load_pending()
    item = pending.get(content_id)
    print(f"ACTION: {action}, CONTENT_ID: {content_id}, ITEM: {item}")
    if action == "approve" and item:
        result = publish_instagram(item["image_url"], item["caption"], item["hashtags"])
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback["id"], "text": "Published to Instagram!"})
        pending.pop(content_id, None)
        save_pending(pending)
        return jsonify({"status": "published", "result": result})
    elif action == "reject":
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback["id"], "text": "Rejected."})
        pending.pop(content_id, None)
        save_pending(pending)
    return jsonify({"ok": True})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "brand": "AiSerena", "chat_id": TELEGRAM_CHAT_ID, "token_set": bool(TELEGRAM_TOKEN)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
