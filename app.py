import os
import json
import uuid
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
INSTAGRAM_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

pending = {}

TRENDS = [
    {"keyword": "minimalist gold ring", "style": "minimal", "palette": "warm gold, ivory"},
    {"keyword": "dainty layered necklace", "style": "elegant", "palette": "gold, cream"},
    {"keyword": "thin stacking rings", "style": "minimal", "palette": "gold, marble"},
    {"keyword": "delicate chain bracelet", "style": "fine", "palette": "gold, linen"},
    {"keyword": "simple hoop earrings", "style": "classic", "palette": "gold, white"},
    {"keyword": "pendant necklace minimal", "style": "modern", "palette": "gold, terracotta"},
    {"keyword": "fine jewelry everyday", "style": "luxury", "palette": "warm gold, nude"},
]

def generate_image_prompt(trend):
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 300,
            "messages": [{
                "role": "user",
                "content": f"Write a gpt-image-1 prompt for a luxury minimalist jewelry product photo. Theme: {trend['keyword']}. Style: {trend['style']}. Colors: {trend['palette']}. Rules: professional product photography, clean background (white marble or cream linen), natural soft light, high-end brand feel, max 2 jewelry pieces, no hands, no models, no people. Return only the prompt text, nothing else, under 100 words."
            }]
        }
    )
    return response.json()["content"][0]["text"].strip()

def generate_image(prompt):
    response = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-image-1",
            "prompt": prompt,
            "size": "1024x1024",
            "quality": "high",
            "n": 1
        }
    )
    data = response.json()
    return data["data"][0]["url"]

def generate_caption(trend):
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 500,
            "messages": [{
                "role": "user",
                "content": f"Write an Instagram caption for a minimalist fine jewelry brand called AiSerena. Theme: {trend['keyword']}. Style: warm, elegant, minimal. 2-3 sentences in English, add 3-4 relevant emojis, end with a CTA like 'Shop the collection, link in bio'. Then add 20 relevant hashtags. Return only JSON: {{\"caption\": \"...\", \"hashtags\": \"#... #...\"}}"
            }]
        }
    )
    raw = response.json()["content"][0]["text"].strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

def send_telegram(content_id, image_url, caption, hashtags):
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"approve:{content_id}"},
            {"text": "❌ Reject", "callback_data": f"reject:{content_id}"}
        ]]
    }
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "photo": image_url,
            "caption": f"New post ready!\n\n{caption}\n\n{hashtags}",
            "reply_markup": keyboard
        }
    )

def publish_instagram(image_url, caption, hashtags):
    full_caption = f"{caption}\n\n{hashtags}"
    r1 = requests.post(
        f"https://graph.facebook.com/v19.0/{INSTAGRAM_ACCOUNT_ID}/media",
        params={"image_url": image_url, "caption": full_caption, "access_token": INSTAGRAM_TOKEN}
    )
    container_id = r1.json().get("id")
    if not container_id:
        return {"error": r1.json()}
    r2 = requests.post(
        f"https://graph.facebook.com/v19.0/{INSTAGRAM_ACCOUNT_ID}/media_publish",
        params={"creation_id": container_id, "access_token": INSTAGRAM_TOKEN}
    )
    return r2.json()

@app.route("/generate", methods=["POST"])
def generate():
    from datetime import date
    day = date.today().weekday()
    trend = TRENDS[day % len(TRENDS)]
    content_id = str(uuid.uuid4())[:8]

    image_prompt = generate_image_prompt(trend)
    image_url = generate_image(image_prompt)
    content = generate_caption(trend)

    pending[content_id] = {
        "image_url": image_url,
        "caption": content["caption"],
        "hashtags": content["hashtags"]
    }

    send_telegram(content_id, image_url, content["caption"], content["hashtags"])
    return jsonify({"status": "sent_for_approval", "content_id": content_id})

@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    callback = data.get("callback_query", {})
    callback_data = callback.get("data", "")
    
    if ":" not in callback_data:
        return jsonify({"ok": True})

    action, content_id = callback_data.split(":", 1)
    item = pending.get(content_id)

    if action == "approve" and item:
        result = publish_instagram(item["image_url"], item["caption"], item["hashtags"])
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback["id"], "text": "Published to Instagram!"}
        )
        pending.pop(content_id, None)
        return jsonify({"status": "published", "result": result})
    elif action == "reject":
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback["id"], "text": "Rejected."}
        )
        pending.pop(content_id, None)

    return jsonify({"ok": True})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "brand": "AiSerena"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
