# WordStream

RSVP-style speed reader: paste text, upload PDF/ePub, or upload MP3 (transcribed with Whisper). Read in the browser with configurable WPM and progress saved to the server.

## Quick start (Docker)

```bash
docker compose up --build
```

Open http://localhost:8080. Data is stored in `./wordstream-data/` (created automatically).

For custom setup, copy `.env.example` to `.env` and adjust values.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_DIR` | `/data` | Directory for database and uploaded files (use `/data` in Docker; bind a volume). |
| `MAX_UPLOAD_MB` | `250` | Max upload size in MB. Uploads are read in chunks and rejected once this limit is exceeded. |
| `CORS_ALLOW_ORIGINS` | `http://localhost:8080,http://127.0.0.1:8080` | Comma-separated allowed browser origins for API access. For LAN clients, add your host/IP origin. |
| `TRANSCRIPTION_STALE_MINUTES` | `30` | Startup recovery threshold for audio docs that were left in processing state. |
| `HF_TOKEN` | — | Optional. [Hugging Face token](https://huggingface.co/settings/tokens) for faster and higher-rate-limit model downloads when transcribing audio. |

For Docker, add to `docker-compose.yml` under `environment`:

```yaml
- HF_TOKEN=your_token_here
```

### LAN usage note

This app is designed for local/internal networks. If clients access via a LAN IP, add that origin to `CORS_ALLOW_ORIGINS`, for example:

```env
CORS_ALLOW_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://192.168.1.20:8080
```

## Running without Docker

1. **Backend:** Python 3.10+, create a venv, install deps, run uvicorn.

   ```bash
   python -m venv venv
   venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   set DATA_DIR=./wordstream-data
   uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
   ```

2. **Frontend:** Build and serve the built files, or run the dev server and proxy API to the backend.

   ```bash
   cd frontend && npm ci && npm run build
   ```

   Serve the `frontend/dist` folder (e.g. with the same app that runs the backend, or nginx) so that `/api` is proxied to the backend. The Docker setup builds the frontend into the image and serves it from FastAPI.

## Features

- **Library:** Paste text, upload PDF, ePub, or MP3. List documents with progress (words read, %).
- **Reader:** RSVP view with optional context strip, WPM control, chapter/page jump. Progress is saved periodically (default every 10 seconds; configurable in the reader, minimum 1 second).
- **Audio:** MP3 uploads are transcribed in the background (faster-whisper). Optional `HF_TOKEN` improves download speed for the model.
- **Recovery:** On startup, stale in-progress transcription jobs are retried or marked with a processing error if required files are missing.

## Tests

- **Backend:** From project root run `pip install -r requirements-dev.txt` then `pytest` (or `python -m pytest tests -v`).
- **Frontend:** In `frontend/` run `npm install` then `npm run test`.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
