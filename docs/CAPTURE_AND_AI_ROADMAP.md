# BATATES — product specification and implementation roadmap

## The user experience: one input, automatic result

The main screen must offer two equally clear ways to start a job:
1. **Paste a live-stream link**.
2. **Upload one or more video files**.

The user should not need to configure OBS for the normal workflow. OBS is an optional capture source for streams that cannot be accessed directly or when the user wants to send a private production feed.

After choosing either input, BATATES should run the same automatic pipeline and produce a reviewable set of finished clips.

## Automatic editing pipeline

For every uploaded video or supported live-stream segment:
1. Ingest media through a permitted source or user-authorized connection.
2. Analyze sampled video frames for scene changes, visible actions, reactions, game events, and other context.
3. Analyze audio for speech, laughter, applause, surprise, and meaningful sound events. Loudness alone must never decide that a moment is a highlight.
4. Transcribe speech with timestamps where supported.
5. Read live chat when the platform exposes an authorized chat API or the user supplies an authorized chat feed. Align chat spikes/repeated reactions with media timestamps. Never promise chat access for platforms or links that do not expose it.
6. Rank candidate moments using visual context, transcript, audio events, and optional chat reactions.
7. Expand each moment to include useful context before and after the event; avoid cutting off the setup or punchline.
8. Assemble multiple selected moments into a coherent montage, remove dead time, and optionally add captions, reframing, transitions, and restrained sound effects.
9. Export ready-to-post versions (vertical 9:16 and landscape 16:9), with editable timeline and per-clip controls.

Every suggested clip should show its timestamps, reason for selection, and confidence so the user can review it.

## Input modes

### 1. Uploaded video files
- Accept one or multiple local files.
- Analyze the full set, not just the currently previewed file.
- Generate multiple candidate moments across the files.
- Build a multi-clip montage with ordering, trimming, and transitions.
- Keep source timestamps and allow the user to change selections before export.

### 2. Live-stream URL
- The user pastes a link; BATATES detects whether the provider and stream format are supported.
- Use only official/authorized APIs or permitted stream access.
- For supported live sources, analyze rolling segments while the stream is live and save highlights as they happen.
- For unsupported, private, login-restricted, DRM-protected, or otherwise inaccessible sources, explain the limitation and offer upload or optional OBS ingest. Do not bypass platform restrictions.

### 3. Optional OBS input
- OBS is an optional fallback/advanced source, not a required step for ordinary uploads or supported stream URLs.
- Use an authenticated RTMP/SRT/WebRTC ingest endpoint to receive the actual video/audio feed.
- OBS WebSocket can support authorized control/status but does not itself carry the video feed.
- Show connection state, latency, dropped frames, and recording/analysis state.

## Chat analysis
- Chat integration is provider-specific and must be authorized.
- Ingest timestamped messages/reaction events where available.
- Detect bursts of repeated reactions and correlate them with the stream timeline.
- Treat chat as a ranking signal, not proof that a moment is funny or important.
- If chat is unavailable, continue video/audio analysis and clearly label chat analysis as unavailable.

## Output and editing
- Produce several clips by default when enough strong moments exist, not only one trim.
- Offer presets such as Best moments, Funny, Action, Surprise, Reaction, and custom keywords.
- Generate captions from speech where transcription is supported; allow correction.
- Provide 9:16 and 16:9 exports.
- Provide a review screen and editable clip timeline before final export.
- Do not add music or effects that obscure speech; keep effects adjustable.

## Architecture required for full functionality
- Android client: input selection, job status, preview, review, timeline editing, export/share.
- Processing service: media ingestion, segmentation, speech transcription, visual/audio analysis, highlight ranking, montage rendering.
- Provider adapters: separate authorized stream and chat connectors per platform.
- Secure job storage and credential handling; never store platform passwords or stream tokens in plain text.
- Clearly label cloud processing, data retention, and any required provider credentials. Prefer local processing when feasible.

## Current implementation status — verified from repository source
- Implemented in the current prototype: local video file selection, preview, manual trim controls, 9:16/16:9 selection, FFmpeg export/share, and an audio-loudness candidate scan.
- Not implemented: pasted live-stream URL ingestion, OBS video ingest, platform chat connectors, semantic visual understanding, speech transcription, multi-file analysis, multi-clip montage, automatic captions, and live background monitoring.
- The current audio scan is only a rough signal detector; it is not semantic AI and cannot reliably identify funny or meaningful moments.
- A backend and provider-specific integrations are required for the full automatic workflow. A mobile APK alone cannot guarantee access to every platform's streams or chat.

## Release acceptance checklist
- [ ] User can choose either Paste stream link or Upload video from the same start screen.
- [ ] Unsupported links fail with a clear explanation and a supported alternative.
- [ ] Uploaded files are analyzed across their full duration and across all selected files.
- [ ] Visual, audio, transcript, and available chat signals are combined.
- [ ] Multiple clips are selected and assembled into a montage.
- [ ] Captions are editable and timestamps are preserved.
- [ ] User can review and edit the timeline before export.
- [ ] Vertical and landscape outputs render and play correctly.
- [ ] Live jobs show connection/analysis state and recover gracefully from disconnects.
- [ ] Automated Android build and a real-device smoke test pass.
