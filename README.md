FacePlay 🎵

Your face is the aux cord.

FacePlay uses real-time face recognition to detect who walks into a room and automatically plays their Spotify song. No app, no phone, no buttons — just walk in.

How It Works

Register your face + a Spotify song via QR code (works from any device, any network)
Walk in front of the camera
Your song plays instantly on Spotify
The display screen shows your name, photo, and album art

Hand gesture control: open hand = volume up, closed fist = volume down.

Demo
DashboardDisplay ScreenManage registered people, view live activity, scan QR to joinFull-screen now-playing view with album art background

Tech Stack

Face Recognition — InsightFace buffalo_l model, cosine similarity matching
Hand Gestures — MediaPipe Hands
Music — Spotify Web API via Spotipy
Tunnel — Cloudflare tunnel for cross-network QR registration
Backend — Flask + Waitress
Frontend — Vanilla HTML/CSS/JS


Setup
Requirements

Python 3.10+
Spotify Premium account
Webcam

Install
bashpip install -r requirements.txt
Configure
Create a .env file:
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://localhost:8888/callback
Get Spotify credentials at developer.spotify.com.
Run
bashpython app.py
Opens at http://localhost:5000 automatically.

Register Someone

Click + Add Person on the dashboard, or
Scan the QR code with any phone (works outside your network)

Enter your name, take/upload a photo, search for your Spotify song, done.

Project Structure
faceplay/
├── app.py              # Main server
├── templates/
│   ├── index.html      # Dashboard
│   ├── display.html    # Now-playing display screen
│   ├── register.html   # Desktop registration
│   └── register_mobile.html  # Mobile registration
├── static/
│   └── photos/         # Registered face photos
├── known_faces.pkl     # Face embeddings (auto-generated)
└── .env                # Spotify credentials (not committed)

Notes

First run downloads the InsightFace model (~300MB), takes a few minutes
Spotify must be open and playing on a device for playback control to work
Face cooldown is 60 seconds to prevent repeated triggering
Runs fully local — no cloud, no data leaves your machine


Built at a hackathon. 🏆
