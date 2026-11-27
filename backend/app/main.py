import json, os, re, shutil, subprocess, threading, uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import cv2
import numpy as np
from .vision import semantic_events
from .chat_connectors import ChatCollector

DATA = Path(os.getenv("BATATES_DATA_DIR", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
JOBS = {}
CHAT_COLLECTORS = {}
LOCK = threading.Lock()
app = FastAPI(title="BATATES AI Processing API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def run(cmd, timeout=3600):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-4000:])
    return p.stdout

def safe_url(value: str) -> str:
    u = urlparse(value)
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https", "rtmp") or not host:
        raise HTTPException(400, "Use a supported public stream URL.")
    if u.scheme == "rtmp":
        allowed = os.getenv("BATATES_MEDIAMTX_HOST", "mediamtx").lower()
        if host != allowed:
            raise HTTPException(400, "RTMP input is restricted to the configured OBS ingest service.")
    elif host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        raise HTTPException(400, "Local network URLs are not accepted.")
    return value

def media_info(path: Path):
    raw = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return max(0.1, float(raw.strip()))

def audio_windows(path: Path, duration: float, window=5.0):
    # RMS energy per window; used as one signal, never as the only highlight criterion.
    values=[]
    for start in np.arange(0, duration, window):
        # Read mean loudness from FFmpeg volumedetect; this is one ranking signal only.
        log=subprocess.run(["ffmpeg","-hide_banner","-nostats","-ss",str(float(start)),"-t",str(min(window,duration-start)),"-i",str(path),"-vn","-af","volumedetect","-f","null","-"],capture_output=True,text=True,timeout=120)
        m=re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB",log.stderr)
        db=float(m.group(1)) if m else -60.0
        values.append((float(start), min(duration,float(start)+window), db))
    return values

def visual_windows(path: Path, duration: float, step=2.0):
    cap=cv2.VideoCapture(str(path))
    if not cap.isOpened(): return []
    samples=[]
    t=0.0
    prev=None
    while t < duration:
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
        ok, frame=cap.read()
        if ok:
            small=cv2.resize(frame,(160,90))
            gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
            hist=cv2.calcHist([gray],[0],None,[32],[0,256])
            cv2.normalize(hist,hist)
            change=float(cv2.compareHist(prev,hist,cv2.HISTCMP_BHATTACHARYYA)) if prev is not None else 0.0
            # motion/change is only a weak visual cue; avoid claiming object-level understanding.
            samples.append((t,change))
            prev=hist
        t+=step
    cap.release()
    return samples

def chat_peaks(chat_path: Optional[Path], duration: float, window=5.0):
    if not chat_path or not chat_path.exists(): return []
    try:
        rows=json.loads(chat_path.read_text(encoding="utf-8"))
    except Exception: return []
    counts={}
    reactions=("lol","lmao","😂","🤣","💀","wow","wtf","no way","pog","!!!","هههه","😭","يا ساتر","مستحيل")
    for row in rows if isinstance(rows,list) else []:
        try:
            sec=max(0.0,min(duration,float(row.get("timestamp",0))))
            bucket=int(sec//window)*window
            message=str(row.get("text","")).lower()
            weight=1.0 + (1.5 if any(token in message for token in reactions) else 0.0)
            counts[bucket]=counts.get(bucket,0.0)+weight
        except Exception: pass
    if not counts: return []
    maximum=max(counts.values()) or 1
    return [(k,min(1.0,v/maximum)) for k,v in counts.items()]

def transcribe(path: Path):
    # Optional model: install faster-whisper and set BATATES_WHISPER_MODEL.
    model_name=os.getenv("BATATES_WHISPER_MODEL","")
    if not model_name: return []
    try:
        from faster_whisper import WhisperModel
        model=WhisperModel(model_name, device=os.getenv("BATATES_WHISPER_DEVICE","cpu"), compute_type=os.getenv("BATATES_WHISPER_COMPUTE","int8"))
        segments,_=model.transcribe(str(path), vad_filter=True)
        return [{"start":float(s.start),"end":float(s.end),"text":s.text.strip()} for s in segments]
    except Exception:
        return []

def analyze(path: Path, jobdir: Path, chat_path: Optional[Path]):
    duration=media_info(path)
    audio=audio_windows(path,duration)
    visual=visual_windows(path,duration)
    chat=chat_peaks(chat_path,duration)
    transcript=transcribe(path)
    try:
        vision=semantic_events(path,duration)
    except Exception as e:
        vision={"enabled":True,"events":[],"reason":str(e)[:300]}
    words=("ضحك","هههه","lol","lmao","laugh","wow","what","no way","amazing","insane","يا ساتر","مستحيل")
    candidates=[]
    for start,end,db in audio:
        center=(start+end)/2
        motion=max((v for t,v in visual if abs(t-center)<=3),default=0.0)
        chat_score=max((v for t,v in chat if abs(t-center)<=5),default=0.0)
        speech=" ".join(x["text"] for x in transcript if x["start"]<end and x["end"]>start)
        text_score=0.5 if any(w in speech.lower() for w in words) else 0.0
        energy=max(0,min(1,(db+55)/45))
        # Weighted multimodal heuristic; visual histogram changes are not semantic object recognition.
        score=100*(0.30*energy+0.25*min(1,motion*2)+0.30*chat_score+0.15*text_score)
        if score>=28:
            candidates.append({"start":max(0,start-2),"end":min(duration,end+3),"score":round(score,1),
                               "signals":{"audio":round(energy,2),"visual_change":round(motion,3),"chat":round(chat_score,2),"transcript_hint":bool(text_score)},
                               "transcript":speech[:300]})
    for event in vision.get("events",[]):
        t=event["time"]
        candidates.append({"start":max(0,t-8),"end":min(duration,t+10),"score":round(event["score"],1),
          "signals":{"semantic_vision":True},"title":event["title"],"reason":event["reason"]})
    # Keep the automatic edit usable for quiet clips or videos without detectable peaks.
    # This is explicitly marked as a fallback, not as an AI-understood highlight.
    if not candidates and duration > 0:
        fallback_length = min(20.0, duration)
        candidates.append({
            "start": 0.0,
            "end": fallback_length,
            "score": 20.0,
            "signals": {"fallback_segment": True},
            "title": "Automatic fallback segment",
            "reason": "No strong highlight signals were detected; exported a starter segment so the job can still complete."
        })
    candidates.sort(key=lambda x:x["score"],reverse=True)
    chosen=[]
    for c in candidates:
        if all(abs(c["start"]-x["start"])>7 for x in chosen):
            chosen.append(c)
        if len(chosen)>=8: break
    chosen.sort(key=lambda x:x["start"])
    return {"duration":duration,"clips":chosen,"transcript":transcript,"chat_available":bool(chat),"vision":vision,"analysis":"Semantic vision when configured, plus audio energy, scene-change, timestamped chat and optional transcript."}

def render(path: Path, clips, out: Path, ratio: str, style: str = "professional"):
    """Free FFmpeg finishing pass: crop, style-specific grade, audio leveling and fades."""
    if style not in ("funny", "gaming", "professional"):
        style = "professional"
    if not clips: raise RuntimeError("No highlight candidates. Try a longer/clearer recording.")
    work=out.parent/"parts"; work.mkdir(exist_ok=True)
    base_vf=("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" if ratio=="9:16"
        else "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
    grades = {
        "funny": "eq=contrast=1.12:saturation=1.28:brightness=0.015,unsharp=5:5:0.65:3:3:0.25",
        "gaming": "eq=contrast=1.18:saturation=1.12:brightness=0.005,unsharp=7:7:0.8:5:5:0.35",
        "professional": "eq=contrast=1.04:saturation=1.05:brightness=0,unsharp=5:5:0.35"
    }
    vf=base_vf+","+grades[style]+",fade=t=in:st=0:d=0.25"
    parts=[]
    for i,c in enumerate(clips):
        part=work/f"{i:02d}.mp4"
        length=max(.5,c["end"]-c["start"])
        audio_filter="loudnorm=I=-16:TP=-1.5:LRA=11,highpass=f=70,acompressor=threshold=0.12:ratio=2.5:attack=20:release=180"
        run(["ffmpeg","-y","-ss",str(c["start"]),"-i",str(path),"-t",str(length),"-vf",vf+",fade=t=out:st="+str(max(0,length-0.25))+":d=0.25","-af",audio_filter,"-r","30","-c:v","libx264","-preset","veryfast","-crf","21","-c:a","aac","-b:a","192k","-movflags","+faststart",str(part)])
        parts.append(part)
    listing=work/"concat.txt"
    listing.write_text("".join("file '"+str(p).replace("'","'\\''")+"'\n" for p in parts),encoding="utf-8")
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(listing),"-c","copy","-movflags","+faststart",str(out)])
    return out

def worker(job_id, source, chat_path, ratio, style="professional"):
    jobdir=DATA/job_id
    try:
        with LOCK: JOBS[job_id]["status"]="analyzing"
        result=analyze(source,jobdir,chat_path)
        with LOCK: JOBS[job_id].update({"status":"rendering","analysis":result})
        output=render(source,result["clips"],jobdir/"BATATES_highlights.mp4",ratio,style)
        with LOCK: JOBS[job_id].update({"status":"complete","download":f"/jobs/{job_id}/download","filename":output.name})
    except Exception as e:
        with LOCK: JOBS[job_id].update({"status":"failed","error":str(e)[:1000]})

def new_job(source: Path, chat_path: Optional[Path], ratio: str):
    job_id=uuid.uuid4().hex[:12]
    with LOCK: JOBS[job_id]={"id":job_id,"status":"queued","created":__import__("time").time(),"source_path":str(source)}
    threading.Thread(target=worker,args=(job_id,source,chat_path,ratio,"professional"),daemon=True).start()
    return {"job_id":job_id,"status":"queued","poll":f"/jobs/{job_id}"}

@app.get("/health")
def health():
    return {"ok":True,"service":"BATATES","features":{"upload":True,"direct_media_url":True,"public_watch_page_resolution":True,"obs_rtmp_ingest":True,"editable_clip_export":True,"semantic_vision_configurable":True,"twitch_chat":True,"youtube_chat":bool(os.getenv("BATATES_YOUTUBE_API_KEY")),"optional_whisper":bool(os.getenv("BATATES_WHISPER_MODEL")),"chunked_live_capture":True}}

@app.post("/jobs/upload")
async def upload_video(video: UploadFile=File(...), chat: Optional[UploadFile]=File(None), ratio: str=Form("9:16"), style: str=Form("professional")):
    if ratio not in ("9:16","16:9"): raise HTTPException(400,"ratio must be 9:16 or 16:9")
    if style not in ("funny","gaming","professional"): raise HTTPException(400,"style must be funny, gaming or professional")
    job_id=uuid.uuid4().hex[:12]; jobdir=DATA/job_id; jobdir.mkdir(parents=True)
    suffix=Path(video.filename or "upload.mp4").suffix.lower()
    if suffix not in (".mp4",".mov",".mkv",".webm",".m4v"): raise HTTPException(400,"Unsupported video format")
    source=jobdir/f"source{suffix}"
    with source.open("wb") as f: shutil.copyfileobj(video.file,f)
    chat_path=None
    if chat:
        chat_path=jobdir/"chat.json"
        chat_path.write_bytes(await chat.read())
    with LOCK: JOBS[job_id]={"id":job_id,"status":"queued","created":__import__("time").time()}
    threading.Thread(target=worker,args=(job_id,source,chat_path,ratio,style),daemon=True).start()
    return {"job_id":job_id,"status":"queued","poll":f"/jobs/{job_id}"}

@app.post("/jobs/stream")
async def stream_url(url: str=Form(...), ratio: str=Form("9:16"),
                     platform: str=Form(""), chat_stream_id: str=Form(""),
                     max_seconds: int=Form(3600)):
    # Direct, authorized media URLs only. Platform watch pages/DRM are not bypassed.
    url=safe_url(url)
    from .stream_sources import classify_page
    inferred_platform,inferred_id=classify_page(url)
    if not platform and inferred_platform:
        platform=inferred_platform
    if not chat_stream_id and inferred_id:
        chat_stream_id=inferred_id
    if ratio not in ("9:16","16:9"): raise HTTPException(400,"ratio must be 9:16 or 16:9")
    max_seconds=max(60,min(max_seconds,7200))
    if platform and platform not in ("twitch","youtube"): raise HTTPException(400,"platform must be twitch or youtube")
    if platform and not chat_stream_id: raise HTTPException(400,"chat_stream_id is required when platform chat is enabled")
    job_id=uuid.uuid4().hex[:12]; jobdir=DATA/job_id; jobdir.mkdir(parents=True)
    with LOCK: JOBS[job_id]={"id":job_id,"status":"capturing","created":__import__("time").time(),"clips_ready":0}
    def capture():
        collector=None
        rendered=[]
        started=__import__("time").time()
        try:
            if platform:
                collector=ChatCollector()
                collector.start(platform,chat_stream_id)
                CHAT_COLLECTORS[job_id]=collector
            chunk_seconds=60
            for index in range(max_seconds//chunk_seconds):
                with LOCK:
                    if JOBS[job_id].get("stop_requested"): break
                    JOBS[job_id]["status"]="capturing"
                    JOBS[job_id]["current_chunk"]=index+1
                source=jobdir/f"live_{index:04d}.mp4"
                try:
                    from .stream_sources import resolve_media_url
                    media_url=resolve_media_url(url)
                    run(["ffmpeg","-y","-i",media_url,"-t",str(chunk_seconds),"-c","copy","-movflags","+faststart",str(source)],timeout=chunk_seconds+45)
                except Exception as e:
                    if not source.exists() or source.stat().st_size<100000:
                        with LOCK: JOBS[job_id]["capture_warning"]=str(e)[:500]
                        break
                if not source.exists() or source.stat().st_size<100000: break
                chat_path=None
                if collector:
                    rows=[{"timestamp":max(0,row["timestamp"]-started-(index*chunk_seconds)),"text":row["text"]}
                          for row in collector.rows if started+(index*chunk_seconds)<=row["timestamp"]<started+((index+1)*chunk_seconds)]
                    chat_path=jobdir/f"chat_{index:04d}.json"
                    chat_path.write_text(json.dumps(rows,ensure_ascii=False),encoding="utf-8")
                with LOCK: JOBS[job_id]["status"]="analyzing_chunk"
                result=analyze(source,jobdir,chat_path)
                if result["clips"]:
                    out=jobdir/f"highlight_{index:04d}.mp4"
                    render(source,result["clips"],out,ratio)
                    rendered.append(out)
                    clip_files=[]
                    for clip_number, candidate in enumerate(result["clips"]):
                        clip_out=jobdir/f"clip_{index:04d}_{clip_number:02d}.mp4"
                        render(source,[candidate],clip_out,ratio)
                        clip_files.append({"file":clip_out.name,"start":candidate["start"],"end":candidate["end"],
                                           "score":candidate["score"],"title":candidate.get("title","Highlight"),
                                           "reason":candidate.get("reason",""),"signals":candidate.get("signals",{})})
                    with LOCK:
                        JOBS[job_id]["clips_ready"]+=len(result["clips"])
                        JOBS[job_id].setdefault("clip_files",[]).extend(clip_files)
                        JOBS[job_id]["latest_analysis"]=result
                        JOBS[job_id]["status"]="clips_available"
                        JOBS[job_id]["latest_clip_index"]=index
                if __import__("time").time()-started>=max_seconds: break
            if collector: collector.stop()
            if not rendered: raise RuntimeError("No highlight clips were found during the live capture.")
            listing=jobdir/"live_concat.txt"
            listing.write_text("".join("file '"+str(p)+"'\n" for p in rendered),encoding="utf-8")
            final=jobdir/"BATATES_highlights.mp4"
            run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(listing),"-c","copy","-movflags","+faststart",str(final)])
            with LOCK: JOBS[job_id].update({"status":"complete","download":f"/jobs/{job_id}/download","filename":final.name,"chat_error":collector.error if collector else None})
        except Exception as e:
            if collector: collector.stop()
            with LOCK: JOBS[job_id].update({"status":"failed","error":str(e)[:1000],"chat_error":collector.error if collector else None})
        finally:
            CHAT_COLLECTORS.pop(job_id,None)
    threading.Thread(target=capture,daemon=True).start()
    return {"job_id":job_id,"status":"capturing","chunk_seconds":60,"max_seconds":max_seconds,
            "chat_enabled":bool(platform),"note":"Captures direct authorized media in 60-second chunks; watch-page URLs may not work.","poll":f"/jobs/{job_id}"}

@app.post("/jobs/{job_id}/stop")
def stop_live_job(job_id: str):
    with LOCK:
        job=JOBS.get(job_id)
        if not job: raise HTTPException(404,"Job not found")
        job["stop_requested"]=True
    collector=CHAT_COLLECTORS.get(job_id)
    if collector: collector.stop()
    return {"job_id":job_id,"stop_requested":True}

@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    with LOCK: job=JOBS.get(job_id)
    if not job: raise HTTPException(404,"Job not found on this server instance")
    return job

@app.get("/jobs/{job_id}/download")
def download(job_id: str):
    with LOCK: job=JOBS.get(job_id)
    if not job or job.get("status")!="complete": raise HTTPException(404,"Output is not ready")
    path=DATA/job_id/"BATATES_highlights.mp4"
    return FileResponse(path,media_type="video/mp4",filename="BATATES_highlights.mp4")


@app.post("/jobs/obs")
async def obs_stream(payload: dict):
    """Start capture from a stream pushed by OBS to the companion MediaMTX RTMP server."""
    import re
    key=str(payload.get("stream_key","")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}",key):
        raise HTTPException(400,"Use an 8-80 character stream key containing letters, numbers, _ or -.")
    ratio=str(payload.get("ratio","9:16"))
    if ratio not in ("9:16","16:9"): raise HTTPException(400,"ratio must be 9:16 or 16:9")
    platform=str(payload.get("platform",""))
    chat_id=str(payload.get("chat_stream_id",""))
    if platform and platform not in ("twitch","youtube"): raise HTTPException(400,"platform must be twitch or youtube")
    if platform and not chat_id: raise HTTPException(400,"chat_stream_id is required when chat is enabled")
    host=os.getenv("BATATES_MEDIAMTX_HOST","mediamtx")
    url=f"rtmp://{host}:1935/live/{key}"
    # Reuse the same live capture worker and authorized chat collector.
    return await stream_url(url,ratio,platform,chat_id,int(payload.get("max_seconds",3600)))


@app.get("/jobs/{job_id}/clips")
def list_job_clips(job_id: str):
    with LOCK: job=JOBS.get(job_id)
    if not job: raise HTTPException(404,"Job not found")
    return {"job_id":job_id,"clips":[{k:v for k,v in item.items() if k!="file"}
            | {"download":f"/jobs/{job_id}/clips/{i}/download"} for i,item in enumerate(job.get("clip_files",[]))]}


@app.get("/jobs/{job_id}/clips/{clip_index}/download")
def download_job_clip(job_id: str,clip_index: int):
    with LOCK: job=JOBS.get(job_id)
    files=job.get("clip_files",[]) if job else []
    if clip_index<0 or clip_index>=len(files): raise HTTPException(404,"Clip not found")
    path=DATA/job_id/files[clip_index]["file"]
    if not path.exists(): raise HTTPException(404,"Clip file is not ready")
    return FileResponse(path,media_type="video/mp4",filename=f"BATATES_clip_{clip_index+1}.mp4")


@app.post("/jobs/{job_id}/edit")
async def edit_job(job_id: str, payload: dict):
    """Re-render selected time ranges from an uploaded source as an editable clip sequence."""
    with LOCK: job=JOBS.get(job_id)
    if not job: raise HTTPException(404,"Job not found")
    source_value=job.get("source_path")
    if not source_value: raise HTTPException(400,"Editing ranges is available for uploaded source videos; select a downloaded live clip for live edits.")
    source=Path(source_value)
    if not source.exists(): raise HTTPException(404,"Original source is no longer available")
    ratio=str(payload.get("ratio","9:16"))
    if ratio not in ("9:16","16:9"): raise HTTPException(400,"ratio must be 9:16 or 16:9")
    requested=payload.get("clips",[])
    if not isinstance(requested,list) or not requested or len(requested)>30: raise HTTPException(400,"Provide 1-30 clip ranges.")
    duration=media_info(source)
    ranges=[]
    for item in requested:
        try:
            start=float(item["start"]); end=float(item["end"])
        except Exception: raise HTTPException(400,"Each clip needs numeric start and end values.")
        if start<0 or end<=start or end>duration: raise HTTPException(400,"Clip range is outside the source video.")
        ranges.append({"start":start,"end":end,"score":100})
    edit_id=uuid.uuid4().hex[:12]
    edit_dir=DATA/job_id/"edits"; edit_dir.mkdir(parents=True,exist_ok=True)
    output=edit_dir/f"{edit_id}.mp4"
    def do_edit():
        try:
            render(source,ranges,output,ratio)
            with LOCK: JOBS[job_id].setdefault("edits",[]).append({"id":edit_id,"file":str(output),"status":"complete"})
        except Exception as exc:
            with LOCK: JOBS[job_id].setdefault("edits",[]).append({"id":edit_id,"status":"failed","error":str(exc)[:500]})
    threading.Thread(target=do_edit,daemon=True).start()
    return {"edit_id":edit_id,"status":"rendering","poll":f"/jobs/{job_id}/edits/{edit_id}"}


@app.get("/jobs/{job_id}/edits/{edit_id}")
def edit_status(job_id: str,edit_id: str):
    with LOCK: job=JOBS.get(job_id)
    if not job: raise HTTPException(404,"Job not found")
    edit=next((x for x in job.get("edits",[]) if x["id"]==edit_id),None)
    if not edit: raise HTTPException(404,"Edit not found")
    return {k:v for k,v in edit.items() if k!="file"} | ({"download":f"/jobs/{job_id}/edits/{edit_id}/download"} if edit.get("status")=="complete" else {})


@app.get("/jobs/{job_id}/edits/{edit_id}/download")
def download_edit(job_id: str,edit_id: str):
    with LOCK: job=JOBS.get(job_id)
    if not job: raise HTTPException(404,"Job not found")
    edit=next((x for x in job.get("edits",[]) if x["id"]==edit_id),None)
    if not edit or edit.get("status")!="complete": raise HTTPException(404,"Edited output is not ready")
    return FileResponse(edit["file"],media_type="video/mp4",filename="BATATES_edited.mp4")
