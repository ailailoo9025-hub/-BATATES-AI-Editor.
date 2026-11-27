# BATATES Processing API (experimental)

## What is implemented
- Video upload and multi-highlight montage rendering.
- Optional semantic frame analysis through an OpenAI-compatible vision API. The server samples up to 12 frames and sends them to the configured provider; no frames leave the server unless the operator sets the vision key/model.
- Audio energy and scene-change signals remain additional ranking signals, not substitutes for semantic understanding.
- Optional timestamped chat JSON for uploaded recordings.
- Live capture of a **direct authorized media URL** in 60-second chunks. Each chunk is analyzed and highlight segments are prepared as capture proceeds; the final montage is assembled when capture stops or reaches its configured limit.
- Twitch IRC and YouTube Live Chat collectors, when their credentials/API access are configured.

## Run locally
Requires Docker and FFmpeg:
```sh
docker build -t batates-api .
docker run --rm -p 8080:8080 -v batates-data:/data \
  -e BATATES_VISION_API_KEY=... \
  -e BATATES_VISION_MODEL=... \
  -e BATATES_TWITCH_OAUTH_TOKEN=... \
  -e BATATES_TWITCH_NICK=... \
  -e BATATES_YOUTUBE_API_KEY=... \
  batates-api
```
Set `BATATES_VISION_BASE_URL` for a compatible provider endpoint other than the default OpenAI API. Vision model selection, provider charges, rate limits and data handling are controlled by the server operator.

## Upload a video
```sh
curl -F "video=@recording.mp4" -F "ratio=9:16" -F "chat=@chat.json" http://localhost:8080/jobs/upload
```
Chat JSON is an array of timestamped messages, for example:
```json
[{"timestamp":42.1,"text":"LOL"}]
```
Poll the returned `poll` path; download from `/jobs/{id}/download`.

## Live direct-media capture
```sh
curl -F "url=https://example.org/authorized/live.m3u8" \
  -F "ratio=9:16" -F "max_seconds=3600" \
  -F "platform=twitch" -F "chat_stream_id=channelname" \
  http://localhost:8080/jobs/stream
```
For YouTube use `platform=youtube` and the live video ID as `chat_stream_id`. Omit platform/chat fields to disable chat collection. Stop early with `POST /jobs/{job_id}/stop`.

**Important:** the media URL must be a direct stream URL the user is authorized to access. A YouTube/Twitch watch-page URL is not a direct media URL; this service does not bypass login, DRM, access controls, or platform restrictions. Chat collection uses official/authorized interfaces and can fail when the stream is not live, chat is disabled, credentials are missing, or API quotas/permissions are insufficient.

## Optional speech transcription
Install `faster-whisper` in the image and set `BATATES_WHISPER_MODEL=small` (or another supported model). This increases image size and CPU/GPU requirements.

## Deployment and security limitations
This is an experimental single-process backend. Before public deployment, add user authentication, HTTPS, quotas, persistent job state, queue workers, SSRF/DNS-rebinding protection, encrypted secret storage, retention/cleanup policies, and monitoring. The Android app needs the deployed HTTPS base URL; localhost defaults are for development only.
