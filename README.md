# YouTube Multi-Channel Automation Studio

A local Python + FastAPI dashboard to connect, analyze, and automate daily uploads for your two English-language YouTube channels:
1. **Kids Channel** (`selfDeclaredMadeForKids=True`)
2. **Games & Movies Channel** (`selfDeclaredMadeForKids=False`)

It tracks trending videos across major English-speaking regions (**US, GB, CA, AU**), pulls your channel analytics, generates AI scripts & SEO metadata from high-velocity trends, and runs a daily upload scheduler.

## Important Platform & Monetization Rules
- **Private Lock Until Audited:** Videos uploaded via `videos.insert` from an unverified Google Cloud project are locked to `private` until your project passes Google's [YouTube API Compliance Audit](https://developers.google.com/youtube/data/guides/quota_and_compliance_audits). Leave `DEFAULT_PRIVACY=private` until approved, then publish or schedule from YouTube Studio.
- **Kids Channel (COPPA):** `selfDeclaredMadeForKids` is automatically set to `True` for the Kids profile. Personalized ads are disabled on Made for Kids content.
- **Games & Movies (Reused Content & Copyright):** Do not upload raw montages of other channels' copyrighted videos. Use `montage_builder.py` only with your own footage, AI-generated clips, royalty-free stock, or Creative Commons clips paired with original voiceover commentary.
- **AI Disclosure:** Set `contains_synthetic_media=True` when uploading realistic AI-generated visuals.

## Quick Setup
1. **Install Python 3.10+** and `ffmpeg` (for `montage_builder.py`).
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Google Cloud Setup:**
   - Create a project in [Google Cloud Console](https://console.cloud.google.com/).
   - Enable **YouTube Data API v3** and **YouTube Analytics API**.
   - Configure the OAuth consent screen (External, add your Google account as a Test User while in testing).
   - Create an **OAuth 2.0 Client ID** (Desktop app) and save the JSON file as `client_secret.json` in this folder.
4. **Environment Variables:**
   ```bash
   cp .env.example .env
   ```
   Add your `GEMINI_API_KEY` inside `.env`.
5. **Run the Dashboard:**
   ```bash
   uvicorn app:app --reload --port 8000
   ```
   Open `http://127.0.0.1:8000` in your browser, connect both channels, and start queueing videos.

## Control from Your Mobile Phone
1. Set `STUDIO_PIN=your_secret_pin` in `.env` so only you can access the dashboard.
2. Start the server listening on your local network:
   ```bash
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```
3. **On the same Wi-Fi:** Open `http://<YOUR_PC_IP>:8000` on your phone browser, enter your PIN, and tap **Add to Home Screen** (works as a standalone web app).
4. **From anywhere (mobile data):** Install [Tailscale](https://tailscale.com/) on both your PC and phone, then open `http://<YOUR_PC_TAILSCALE_IP>:8000` securely from anywhere without opening router ports.
