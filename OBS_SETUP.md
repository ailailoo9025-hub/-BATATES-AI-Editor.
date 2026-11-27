# BATATES OBS ingest (MediaMTX)

Run the API and MediaMTX together:
```sh
docker compose -f docker-compose.obs.yml up --build
```

In OBS → Settings → Stream:
- Service: Custom
- Server: `rtmp://YOUR_SERVER_HOST:1935/live`
- Stream key: a long private key of your choice (example: `my-private-key`)

In BATATES, use the OBS ingest endpoint with that key. The API pulls
`rtmp://mediamtx:1935/live/<key>`, analyzes it in 60-second chunks, and
publishes each finished highlight in the live job's clips list. Keep the
stream key private; use a firewall to restrict RTMP port 1935 and HTTPS
for the public API. OBS ingest is an RTMP push; SRT is not enabled in this
starter deployment.

Platform page extraction uses yt-dlp for publicly accessible Twitch/YouTube
streams only. It does not bypass DRM, private streams, login requirements,
or other platform controls. Platform terms and rights still apply.
