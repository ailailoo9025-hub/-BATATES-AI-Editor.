# BATATES capture and AI roadmap

This document defines the intended product behavior. It is a roadmap, not a claim that every feature is already implemented.

## Three capture modes

### A. Uploaded / local videos
- Select one or many local video files.
- Analyze each asset and produce a ranked candidate list with timestamps.
- Combine selected moments into a vertical or landscape short.
- Preserve source references and allow manual trim adjustments.
- Current prototype: local file import, preview, manual trim, one-clip export, and audio-energy candidate scan. It does not yet perform semantic visual understanding or multi-clip montage editing.

### B. Stream URL
- Accept a stream URL only for providers and stream formats that permit authorized access.
- Resolve the stream through an approved provider API or a user-authorized ingest endpoint.
- Do not bypass DRM, login restrictions, paywalls, platform safeguards, or download restrictions.
- Analyze rolling segments while the stream is live, retain a configurable buffer, and save candidate timestamps.
- If a platform blocks direct ingest, instruct the user to use OBS or a supported relay instead.

### C. OBS live input
- Preferred implementation: OBS sends an authenticated stream to a local or cloud ingest service (for example, an RTMP/SRT/WebRTC endpoint).
- The service segments the feed, analyzes video/audio, and returns candidate moments to the app.
- OBS WebSocket may be used for user-authorized scene/source control and status, but it is not itself the video transport.
- Display connection status, dropped frames, latency, and recording state.

## AI analysis pipeline
1. Scene sampling and visual event detection.
2. Speech-to-text with timestamps and speaker segmentation where supported.
3. Audio event and excitement scoring (laughter, applause, surprise, shouting, game sounds); loudness alone is not enough.
4. Multimodal ranking using visual context, transcript, audio events, and optional chat reactions.
5. Candidate explanation: why selected, start/end timestamps, confidence, and detected event.
6. Human review and editable timeline before export.

## Product behavior
- Every candidate is reviewable and editable.
- Provide "best moments", "funny", "action", "surprise", "reaction", and custom search modes.
- Never claim a moment is funny or important based only on volume.
- Offer local/on-device processing where feasible and clearly label cloud processing and any required API credentials.
- Do not collect stream credentials in plain text; use secure credential storage and least-privilege access.

## Current implementation status
- Available in prototype: local video selection, preview, trim controls, aspect-ratio choice, FFmpeg export/share, audio loudness window scan.
- Not implemented yet: direct platform stream ingest, OBS ingest, semantic vision model, speech transcription, chat reaction analysis, multi-clip timeline/montage, background live monitoring.
- The Android app alone cannot reliably ingest every platform URL. A companion ingest/analysis service and provider-specific integrations are required.
