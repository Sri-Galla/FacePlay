# FacePlay #

FacePlay uses face recognition to detect who walks into a room and automatically plays their Spotify song.

### How It Works ###

- Register your face + a Spotify song via QR code or the dashboard
- Walk in front of the camera
- Your song plays instantly on Spotify
- The display screen shows your name, photo, and album art

#### Adjust volume with hand gestures: 
- open hand = volume up
- close fist = volume down.

### Tech Stack ###
- Face Recognition - InsightFace buffalo_l model, cosine similarity matching
- Hand Gestures - MediaPipe Hands
- Music - Spotify Web API via Spotipy
- Tunnel - Cloudflare tunnel for cross-network QR registration
- Backend - Flask + Waitress
- Frontend - Vanilla HTML/CSS/JS

### Setup Requirements ###

- Python 3.10+
- Spotify Premium account
- Webcam

### Installation ###
- bashpip install -r requirements.txt
- Configure
- Create a .env file:
- SPOTIFY_CLIENT_ID=your_client_id
- SPOTIFY_CLIENT_SECRET=your_client_secret
- SPOTIFY_REDIRECT_URI=http://localhost:8888/callback

Get Spotify credentials at developer.spotify.com.

### Run ###
- bashpython app.py
- Opens at http://localhost:5000 automatically.

### Register Someone ###

Click + Add Person on the dashboard, or scan the QR code with any phone. 
Enter your name, take/upload a photo, search for your Spotify song, and jam.

### Project Structure ###
```
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
```
#### Notes ###

- First run downloads the InsightFace model (~300MB), takes a few minutes
- Spotify must be downloaded and will automatically launch with application
- Face cooldown is 60 seconds to prevent repeated triggering. Tune according to personal preferences.
- Runs fully local


Built at a hackathon. 🏆
