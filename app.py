import os
import subprocess
import glob
import time
import threading
import logging
import json
import requests
from flask import Flask, request, jsonify

# ========== HARDCODED CREDS ==========
BOT_TOKEN = "8565401094:AAFG3L4moBXsGSvqb8PaHd4lffJxCOSgpyg"
ALLOWED_USER_ID = 8518164866
YOUTUBE_STREAM_KEY = "2s3r-8v7c-8mcs-g7s3-ck6y"
VIDEO_DIR = "/app/videos"
PLAYLIST_FILE = "/app/playlist.txt"
LOG_FILE = "/app/streamer.log"

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
YT_RTMP = f"rtmp://a.rtmp.youtube.com/live2/{YOUTUBE_STREAM_KEY}"

stream_process = None
is_streaming = False
current_video = None

# ========== LOGGING ==========
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)

def log(msg):
    logging.info(msg)
    print(msg)

# ========== TELEGRAM SEND MESSAGE ==========
def send_tg_message(chat_id, text):
    url = f"{TG_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log(f"TG send error: {e}")

# ========== FFMPEG STREAM CONTROLLER ==========
def start_ffmpeg_stream(video_path):
    global stream_process, is_streaming, current_video
    stop_ffmpeg_stream()
    
    cmd = [
        "ffmpeg", "-re", "-stream_loop", "-1",
        "-i", video_path,
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", "2500k", "-maxrate", "2500k",
        "-bufsize", "5000k",
        "-pix_fmt", "yuv420p",
        "-g", "60",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-f", "flv", YT_RTMP
    ]
    
    try:
        stream_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        is_streaming = True
        current_video = video_path
        log(f"Stream started: {video_path}")
        return True
    except Exception as e:
        log(f"FFmpeg start error: {e}")
        return False

def stop_ffmpeg_stream():
    global stream_process, is_streaming, current_video
    if stream_process:
        try:
            stream_process.terminate()
            stream_process.wait(timeout=5)
        except:
            stream_process.kill()
        stream_process = None
    is_streaming = False
    current_video = None
    log("Stream stopped")

def update_playlist_file():
    videos = glob.glob(f"{VIDEO_DIR}/*.mp4") + glob.glob(f"{VIDEO_DIR}/*.mkv") + glob.glob(f"{VIDEO_DIR}/*.webm")
    with open(PLAYLIST_FILE, "w") as f:
        for v in videos:
            f.write(f"file '{v}'\n")
    return videos

# ========== FLASK APP ==========
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    
    if "message" not in data:
        return "ok"
    
    msg = data["message"]
    chat_id = msg.get("chat", {}).get("id")
    user_id = msg.get("from", {}).get("id")
    text = msg.get("text", "")
    
    if user_id != ALLOWED_USER_ID:
        send_tg_message(chat_id, "Unauthorized")
        return "ok"
    
    # /start command
    if text == "/start":
        send_tg_message(chat_id, "Bot ready. Send video file to stream.")
    
    # /stop command
    elif text == "/stop":
        stop_ffmpeg_stream()
        send_tg_message(chat_id, "Stream stopped")
    
    # /status command
    elif text == "/status":
        status_msg = f"Streaming: {is_streaming}\n"
        if current_video:
            status_msg += f"Current: {os.path.basename(current_video)}"
        send_tg_message(chat_id, status_msg)
    
    # /logs command
    elif text == "/logs":
        try:
            with open(LOG_FILE, "r") as f:
                lines = f.readlines()[-10:]
            send_tg_message(chat_id, "".join(lines) if lines else "No logs")
        except:
            send_tg_message(chat_id, "Log file not found")
    
    # /list command
    elif text == "/list":
        videos = update_playlist_file()
        if videos:
            msg = "Videos:\n" + "\n".join([os.path.basename(v) for v in videos])
        else:
            msg = "No videos in directory"
        send_tg_message(chat_id, msg)
    
    # /stream <filename> command
    elif text.startswith("/stream "):
        filename = text.replace("/stream ", "").strip()
        video_path = os.path.join(VIDEO_DIR, filename)
        if os.path.exists(video_path):
            if start_ffmpeg_stream(video_path):
                send_tg_message(chat_id, f"Streaming: {filename}")
            else:
                send_tg_message(chat_id, "Failed to start stream")
        else:
            send_tg_message(chat_id, f"File not found: {filename}")
    
    # video file upload handler
    elif "video" in msg:
        file_id = msg["video"]["file_id"]
        file_name = msg["video"].get("file_name", f"{file_id}.mp4")
        
        # get file path from telegram
        get_file_url = f"{TG_API}/getFile?file_id={file_id}"
        resp = requests.get(get_file_url).json()
        
        if "result" in resp:
            file_path = resp["result"]["file_path"]
            download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            
            # download video
            send_tg_message(chat_id, f"Downloading: {file_name}")
            video_data = requests.get(download_url).content
            
            save_path = os.path.join(VIDEO_DIR, file_name)
            with open(save_path, "wb") as f:
                f.write(video_data)
            
            update_playlist_file()
            send_tg_message(chat_id, f"Saved: {file_name}")
            
            # auto start if no stream running
            if not is_streaming:
                if start_ffmpeg_stream(save_path):
                    send_tg_message(chat_id, f"Auto-streaming: {file_name}")
    
    return "ok"

@app.route("/ping", methods=["GET"])
def ping():
    return "pong"

# ========== KEEP ALIVE THREAD (RENDER SLEEP BYPASS) ==========
def keep_alive():
    while True:
        time.sleep(300)  # 5 min
        try:
            requests.get("https://your-app-name.onrender.com/ping", timeout=10)
        except:
            pass

# ========== MAIN ==========
if __name__ == "__main__":
    os.makedirs(VIDEO_DIR, exist_ok=True)
    update_playlist_file()
    
    # start keep-alive thread
    threading.Thread(target=keep_alive, daemon=True).start()
    
    log("Bot starting...")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
