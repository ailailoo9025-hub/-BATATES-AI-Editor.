# BATATES Processing API (experimental)

This service adds real server-side processing for BATATES:
- Uploaded video analysis and multi-highlight montage rendering.
- Optional timestamped chat JSON, aligned to media time.
- Audio-energy and visual scene-change signals.
- Optional Faster-Whisper transcript signal.
- Authorized direct media URL capture (bounded to 10 minutes).

## Run locally
Requires Docker and a machine with FFmpeg. From this folder:
```sh
docker build -t batates-api .
docker run --rm -p 8080:8080 -v batates-data:/data batates-api
```
Health: `http://localhost:8080/health`.

Upload:
```sh
curl -F "video=@recording.mp4" -F "ratio=9:16" -F "chat=@chat.json" http://localhost:8080/jobs/upload
```
Chat JSON is an array of objects with numeric `timestamp` in seconds and `message`, e.g.
`[{"timestamp":42.1,"message":"LOL"}]`.
Poll the returned `poll` path; download from `/jobs/{id}/download`.

Direct stream:
```sh
curl -F "url=https://example.org/authorized/live.m3u8" -F "ratio=9:16" http://localhost:8080/jobs/stream
```
This is for direct media URLs the user is authorized to access. It does not extract media from platform watch pages, defeat DRM, bypass login, or read platform chat. Provider-specific chat adapters and continuous live rolling capture are not included yet.

## Optional speech transcription
Install `faster-whisper` in the image and set `BATATES_WHISPER_MODEL=small` (or another supported model). This increases image size and CPU/GPU requirements. Without it, the pipeline still analyzes audio energy, visual scene changes, and supplied chat.

## Current limitations
- Scene-change analysis is not object/action understanding; no general semantic vision model is bundled.
- Chat is accepted as a timestamped JSON sidecar; no Twitch/YouTube/Kick provider connector is bundled.
- Stream capture is a single bounded 10-minute segment, not an always-on live monitor.
- One worker thread per job; not production queueing or multi-user security. Add authentication, quotas, persistent job storage, SSRF protection, encrypted secrets, cleanup policy, and a queue before public deployment.
- This API is an experimental processing backend and must be deployed to a reachable HTTPS host before the Android app can use it.
