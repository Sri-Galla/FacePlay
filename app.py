"""
app.py — FacePlay main server.
Hand volume control: open hand = loud, closed fist = quiet.
"""

import cv2
import numpy as np
import pickle
import os
import time
import threading
import base64
import qrcode
import io
import socket
import subprocess
import webbrowser
import re

import pygame
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from insightface.app import FaceAnalysis
from dotenv import load_dotenv
import mediapipe as mp
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

load_dotenv()

ENCODINGS_FILE  = "known_faces.pkl"
COOLDOWN        = 10
SIMILARITY_THRESHOLD = 0.65
PROCESS_EVERY_N = 5
DISPLAY_DURATION = 240
SONG_BUFFER     = COOLDOWN
UPLOAD_FOLDER   = "static/photos"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs("songs", exist_ok=True)

app = Flask(__name__)
CORS(app)

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
    scope="user-read-playback-state user-modify-playback-state user-read-currently-playing"
))

# ── pycaw volume ──────────────────────────────────────────────────────────────
_vol_interface = None

def _init_vol():
    global _vol_interface
    try:
        d = AudioUtilities.GetSpeakers()
        raw = d._dev if hasattr(d, '_dev') else d
        _vol_interface = cast(raw.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
                              POINTER(IAudioEndpointVolume))
        print("Volume ready.")
    except Exception as e:
        print(f"Volume init error: {e}")

def set_volume(level):
    if _vol_interface is None: return
    try: _vol_interface.SetMasterVolumeLevelScalar(max(0, min(100, int(level))) / 100.0, None)
    except: pass

def get_volume():
    if _vol_interface is None: return 50
    try: return int(_vol_interface.GetMasterVolumeLevelScalar() * 100)
    except: return 50

_init_vol()

# ── smooth volume glide thread ────────────────────────────────────────────────
_target_vol        = get_volume()
_current_smooth_vol = float(_target_vol)

def _vol_thread():
    global _current_smooth_vol
    while True:
        _current_smooth_vol += (_target_vol - _current_smooth_vol) * 0.08
        v = int(round(_current_smooth_vol))
        if abs(v - get_volume()) > 1.5:
            set_volume(v)
        time.sleep(0.03)

threading.Thread(target=_vol_thread, daemon=True).start()

# ── InsightFace mutex ─────────────────────────────────────────────────────────
_face_lock = threading.Lock()

# ── Simple TTL cache helper ───────────────────────────────────────────────────
class TTLCache:
    def __init__(self, ttl):
        self.ttl   = ttl
        self.value = None
        self.ts    = 0
        self.lock  = threading.Lock()

    def get(self, fetcher):
        now = time.time()
        with self.lock:
            if self.value is not None and now - self.ts < self.ttl:
                return self.value
        try:
            val = fetcher()
        except Exception as e:
            print(f"TTLCache fetch error: {e}")
            with self.lock:
                return self.value
        with self.lock:
            self.value = val
            self.ts    = time.time()
        return val

    def invalidate(self):
        with self.lock:
            self.ts = 0

_devices_cache     = TTLCache(ttl=20)
_now_playing_cache = TTLCache(ttl=4)

# ── QR code ───────────────────────────────────────────────────────────────────
_qr_data = {"qr": None, "url": ""}

def _make_qr(url):
    """Build QR image from any URL and store in _qr_data."""
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    _qr_data["qr"]  = base64.b64encode(buf.read()).decode()
    _qr_data["url"] = url
    print(f"QR URL: {url}")

def _start_tunnel():
    """Start cloudflared tunnel and grab public URL from its stderr output."""
    try:
        proc = subprocess.Popen(
            [r"C:\Program Files (x86)\cloudflared\cloudflared.exe", "tunnel", "--url", "http://localhost:5000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        for line in proc.stderr:
            line = line.decode("utf-8", errors="ignore")
            match = re.search(r'https://[a-z0-9\-]+\.trycloudflare\.com', line)
            if match:
                public_url = match.group(0) + "/register/mobile"
                _make_qr(public_url)
                return
    except FileNotFoundError:
        print("cloudflared not found — falling back to local IP QR")
    except Exception as e:
        print(f"Tunnel error: {e}")

    # Fallback: local IP
    try:
        ip = socket.gethostbyname(socket.gethostname())
        _make_qr(f"http://{ip}:5000/register/mobile")
    except Exception as e:
        print(f"QR fallback error: {e}")

threading.Thread(target=_start_tunnel, daemon=True).start()

# ── Known faces — memory cache, only re-reads file when it changes ────────────
_faces_cache       = None
_faces_cache_mtime = 0

def load_known_faces():
    global _faces_cache, _faces_cache_mtime
    try:
        mtime = os.path.getmtime(ENCODINGS_FILE) if os.path.exists(ENCODINGS_FILE) else 0
        if _faces_cache is not None and mtime == _faces_cache_mtime:
            return _faces_cache
        if not os.path.exists(ENCODINGS_FILE):
            _faces_cache = []; return _faces_cache
        with open(ENCODINGS_FILE, "rb") as f:
            _faces_cache = pickle.load(f)
        _faces_cache_mtime = mtime
        return _faces_cache
    except:
        return _faces_cache or []

def save_known_faces(faces):
    global _faces_cache, _faces_cache_mtime
    with open(ENCODINGS_FILE, "wb") as f:
        pickle.dump(faces, f)
    _faces_cache      = faces
    _faces_cache_mtime = os.path.getmtime(ENCODINGS_FILE)

# ── App state ─────────────────────────────────────────────────────────────────
state = {
    "current_person": None,
    "current_song":   None,
    "last_seen":      [],
    "last_played":    {},
    "display_until":  0,
    "volume_display": "",
    "volume_display_until": 0,
}
state_lock = threading.Lock()

print("Loading InsightFace...")
face_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
face_app.prepare(ctx_id=0, det_size=(640, 640))
print("Model ready.")

mp_hands = mp.solutions.hands
pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.mixer.init()

# ── Helpers ───────────────────────────────────────────────────────────────────
def cosine_distance(a, b):
    a = a / np.linalg.norm(a); b = b / np.linalg.norm(b)
    return 1 - np.dot(a, b)

def match_face(emb, known):
    best_name, best_data, best_dist = None, None, float("inf")
    for p in known:
        d = cosine_distance(emb, p["embedding"])
        if d < best_dist:
            best_dist = d; best_name = p["name"]; best_data = p
    if best_dist < SIMILARITY_THRESHOLD: return best_name, best_data, best_dist
    return None, None, None

SPOTIFY_EXE = os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")

def launch_spotify():
    try:
        if os.path.exists(SPOTIFY_EXE): subprocess.Popen([SPOTIFY_EXE])
        else: os.startfile("spotify:")
    except Exception as e: print(f"Spotify launch error: {e}")

def play_spotify(uri, device_id=None):
    try:
        available = _devices_cache.get(lambda: sp.devices().get("devices", []))
        if not available:
            launch_spotify(); time.sleep(4)
            _devices_cache.invalidate()
            available = _devices_cache.get(lambda: sp.devices().get("devices", []))
        if not available: return False
        active = [d for d in available if d.get("is_active")]
        target = device_id or (active[0]["id"] if active else available[0]["id"])
        sp.start_playback(device_id=target, uris=[uri])
        _now_playing_cache.invalidate()
        return True
    except Exception as e:
        print(f"Spotify error: {e}"); return False

def play_local(path, name):
    if not os.path.exists(path): return
    try:
        pygame.mixer.music.stop()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
    except Exception as e: print(f"Audio error: {e}")

def trigger_song(person_data, name):
    song = person_data.get("song", "")
    if song.startswith("spotify:track:"):
        if not play_spotify(song):
            local = person_data.get("local_song", "")
            if local: play_local(local, name)
    else:
        play_local(song, name)

def get_hand_spread(hl, w, h):
    lm = hl.landmark
    def pt(i): return np.array([lm[i].x * w, lm[i].y * h])
    spread    = np.linalg.norm(pt(4) - pt(20))
    hand_size = np.linalg.norm(pt(12) - pt(0))
    if hand_size < 1e-5: return None
    return max(0.0, min(1.0, (spread / hand_size - 0.3) / (1.4 - 0.3)))

# ── Main camera loop ──────────────────────────────────────────────────────────
def main_loop():
    global _target_vol
    cap = cv2.VideoCapture(0)
    if not cap.isOpened(): print("ERROR: Webcam not found."); return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    hands      = mp_hands.Hands(static_image_mode=False, max_num_hands=1,
                                 min_detection_confidence=0.7, min_tracking_confidence=0.6)
    frame_count = 0
    ema_spread  = None
    last_log    = 0
    EMA_ALPHA   = 0.12

    print("Main loop started.")
    while True:
        ret, frame = cap.read()
        if not ret: time.sleep(0.05); continue

        frame_count += 1
        now = time.time()
        h, w = frame.shape[:2]

        hand_results = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        if hand_results.multi_hand_landmarks:
            for hl in hand_results.multi_hand_landmarks:
                spread = get_hand_spread(hl, w, h)
                if spread is not None:
                    ema_spread = spread if ema_spread is None else EMA_ALPHA * spread + (1 - EMA_ALPHA) * ema_spread
                    _target_vol = int(ema_spread * 100)
                    if now - last_log > 0.5:
                        print(f"Vol: {_target_vol}%")
                        last_log = now
                        with state_lock:
                            state["volume_display"]       = f"Volume: {_target_vol}%"
                            state["volume_display_until"] = now + 1.5
        else:
            ema_spread = None

        if frame_count % PROCESS_EVERY_N != 0:
            continue

        known = load_known_faces()
        if not known: continue

        if _face_lock.acquire(blocking=False):
            try:
                for face in face_app.get(frame):
                    name, pdata, dist = match_face(face.embedding, known)
                    with state_lock:
                        last_any = max(state["last_played"].values()) if state["last_played"] else 0
                        is_new   = name != state["current_person"]
                        if not is_new and now - last_any < SONG_BUFFER: continue
                        last = state["last_played"].get(name or "__unknown__", 0)
                        if now - last > COOLDOWN:
                            if name and pdata:
                                # update state immediately so display shows instantly
                                state["last_played"][name] = now
                                state["current_person"]    = name
                                state["current_song"]      = pdata.get("song_name", "Unknown")
                                state["display_until"]     = now + DISPLAY_DURATION
                                state["last_seen"].insert(0, {"name": name, "time": time.strftime("%H:%M:%S"), "photo": pdata.get("photo", "")})
                                state["last_seen"]         = state["last_seen"][:10]
                                # play song in background so Spotify latency never blocks display
                                threading.Thread(target=trigger_song, args=(pdata, name), daemon=True).start()
                            else:
                                if os.path.exists("songs/unknown.mp3"): play_local("songs/unknown.mp3", "???")
                                state["last_played"]["__unknown__"] = now
                                state["current_person"] = "???"
                                state["current_song"]   = "Who are you?"
                                state["display_until"]  = now + DISPLAY_DURATION
            finally:
                _face_lock.release()

    cap.release(); hands.close()

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index(): return render_template("index.html")

@app.route("/display")
def display(): return render_template("display.html")

@app.route("/register")
def register_page(): return render_template("register.html")

@app.route("/register/mobile")
def register_mobile(): return render_template("register_mobile.html")

# Serve photos directly for fast loading
@app.route("/static/photos/<filename>")
def serve_photo(filename):
    path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(path):
        return send_file(path)
    return "", 404

@app.route("/api/register/qr")
def register_qr():
    if not _qr_data["qr"]:
        return jsonify({"qr": "", "url": "Loading..."}), 202
    return jsonify(_qr_data)

@app.route("/api/register", methods=["POST"])
def api_register():
    name       = request.form.get("name", "").strip()
    song_uri   = request.form.get("song_uri", "").strip()
    song_name  = request.form.get("song_name", "Unknown").strip()
    photo_file = request.files.get("photo")
    if not name or not photo_file:
        return jsonify({"error": "Name and photo required"}), 400

    photo_path = f"{UPLOAD_FOLDER}/{name.lower().replace(' ', '_')}.jpg"
    photo_file.save(photo_path)
    img = cv2.imread(photo_path)
    if img is None:
        return jsonify({"error": "Could not read photo"}), 400

    with _face_lock:
        try:
            faces = face_app.get(img)
        except Exception as e:
            return jsonify({"error": f"Detection failed: {e}"}), 500

    if not faces:
        return jsonify({"error": "No face detected. Try better lighting."}), 400
    if len(faces) > 1:
        return jsonify({"error": "Multiple faces detected. Use a solo photo."}), 400

    if not song_uri:
        song_uri  = "spotify:track:4cOdK2wGLETKBW3PvgPWqT"
        song_name = "Never Gonna Give You Up - Rick Astley"

    known = load_known_faces()
    known = [p for p in known if p["name"].lower() != name.lower()]
    known.append({"name": name, "embedding": faces[0].embedding, "song": song_uri,
                  "song_name": song_name, "photo": f"/static/photos/{name.lower().replace(' ', '_')}.jpg"})
    save_known_faces(known)
    return jsonify({"success": True, "name": name, "song": song_name})

@app.route("/api/search_song")
def search_song():
    q = request.args.get("q", "")
    if not q: return jsonify([])
    try:
        results = sp.search(q=q, type="track", limit=5)
        return jsonify([{"uri": t["uri"], "name": t["name"], "artist": t["artists"][0]["name"],
                         "album_art": t["album"]["images"][0]["url"] if t["album"]["images"] else ""}
                        for t in results.get("tracks", {}).get("items", [])])
    except Exception as e:
        print(f"Search error: {e}"); return jsonify({"error": str(e)}), 500

@app.route("/api/state")
def api_state():
    with state_lock:
        return jsonify({**state, "now": time.time()})

@app.route("/api/people")
def api_people():
    return jsonify([{"name": p["name"], "song_name": p.get("song_name", ""), "photo": p.get("photo", "")}
                    for p in load_known_faces()])

@app.route("/api/delete/<n>", methods=["DELETE"])
def delete_person(name):
    save_known_faces([p for p in load_known_faces() if p["name"].lower() != name.lower()])
    return jsonify({"success": True})

@app.route("/api/update_song", methods=["POST"])
def update_song():
    data  = request.get_json()
    name  = data.get("name", "").strip()
    uri   = data.get("song_uri", "").strip()
    sname = data.get("song_name", "").strip()
    if not name or not uri: return jsonify({"error": "Name and song required"}), 400
    known = load_known_faces()
    for p in known:
        if p["name"].lower() == name.lower():
            p["song"] = uri; p["song_name"] = sname
            save_known_faces(known); return jsonify({"success": True})
    return jsonify({"error": "Person not found"}), 404

@app.route("/api/devices")
def api_devices():
    return jsonify(_devices_cache.get(lambda: sp.devices().get("devices", [])))

@app.route("/api/now_playing")
def api_now_playing():
    def fetch():
        current = sp.current_playback()
        if current and current.get("item"):
            item = current["item"]; images = item.get("album", {}).get("images", [])
            return {"album_art": images[0]["url"] if images else None,
                    "track": item["name"], "artist": item["artists"][0]["name"]}
        return {"album_art": None}
    return jsonify(_now_playing_cache.get(fetch))

@app.route("/api/volume")
def api_volume():
    return jsonify({"volume": get_volume()})

# Skip cloudflared browser warning
@app.after_request
def add_tunnel_headers(response):
    response.headers['ngrok-skip-browser-warning'] = 'true'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

if __name__ == "__main__":
    threading.Thread(target=main_loop, daemon=True).start()
    print("\nFacePlay running at http://localhost:5000")
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5000")).start()
    from waitress import serve
    serve(app, host="0.0.0.0", port=5000, threads=16)