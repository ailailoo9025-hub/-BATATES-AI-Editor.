# BATATES MediaMTX deployment (tablet-friendly)

## What this adds
A dedicated MediaMTX RTMP ingest service for OBS or another RTMP publisher. The FastAPI service remains separate. This does NOT by itself make the current Render free web service suitable for 24/7 live processing.

## Deploy from a tablet
1. Open the BATATES GitHub repository in your browser.
2. Confirm these files exist: `mediamtx.yml`, `Dockerfile.mediamtx`, and `render-mediamtx.yaml`.
3. In Render Dashboard choose **New +** then **Private Service** (if available for your account) and connect this repository.
4. Set runtime to Docker, Dockerfile path to `Dockerfile.mediamtx`, Docker context to repository root.
5. For public RTMP publishing, use a service that supports public TCP port 1935. Render private services are not publicly reachable from streaming apps; Render web services primarily expose HTTP and are not a drop-in public RTMP endpoint. Use a provider that explicitly supports TCP ingress or a VPS if Render cannot expose TCP 1935.
6. Once deployed on a TCP-capable host, set the service's public hostname and port in BATATES backend environment:
   - `BATATES_MEDIAMTX_HOST=<the MediaMTX hostname>`
   - `BATATES_MEDIAMTX_PUBLISH_URL=rtmp://<the MediaMTX hostname>:1935/live`
7. Set the backend's ingest URL and access policy before exposing it publicly. Do not publish a stream key in screenshots or public repositories.

## OBS / encoder
Server: `rtmp://<MediaMTX-host>:1935/live`
Stream key: a long random secret assigned for your stream.
Publish path: `/live/<stream-key>`

## Playback
HLS playback is available at `http://<MediaMTX-host>:8888/live/<stream-key>/index.m3u8` only if HLS is enabled and exposed by the host.

## Important
- A Render free web service is not sufficient for public RTMP ingest or reliable continuous streams.
- Render private services are private network services, not public RTMP endpoints.
- Keep the stream key secret. Restrict publisher access and configure TLS / firewall rules on the selected host.
- This configuration is an initial deployment scaffold; test RTMP publishing and HLS playback before connecting BATATES automatic clip capture.
