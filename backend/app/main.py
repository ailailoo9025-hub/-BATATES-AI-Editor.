import json, os, re, shutil, subprocess, threading, uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import cv2
import numpy as np

DATA = Path(os.getenv("BATATES_DATA_DIR", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
JOBS = {}
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
    if u.scheme not in ("http", "https") or not u.hostname:
        raise HTTPException(400, "Use a valid http(s) media URL.")
    host = u.hostname.lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
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
    for row in rows if isinstance(rows,list) else []:
        try:
            sec=max(0.0,min(duration,float(row.get("timestamp",0))))
            bucket=int(sec//window)*window
            counts[bucket]=counts.get(bucket,0)+1
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
    candidates.sort(key=lambda x:x["score"],reverse=True)
    chosen=[]
    for c in candidates:
        if all(abs(c["start"]-x["start"])>7 for x in chosen):
            chosen.append(c)
        if len(chosen)>=8: break
    chosen.sort(key=lambda x:x["start"])
    return {"duration":duration,"clips":chosen,"transcript":transcript,"chat_available":bool(chat),"analysis":"Audio energy + visual scene-change + optional timestamped chat + optional transcript. Not a semantic vision model."}

def render(path: Path, clips, out: Path, ratio: str):
    if not clips: raise RuntimeError("No highlight candidates. Try a longer/clearer recording.")
    work=out.parent/"parts"; work.mkdir(exist_ok=True)
    vf=("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" if ratio=="9:16"
        else "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
    parts=[]
    for i,c in enumerate(clips):
        part=work/f"{i:02d}.mp4"
        run(["ffmpeg","-y","-ss",str(c["start"]),"-i",str(path),"-t",str(max(.5,c["end"]-c["start"])),"-vf",vf,"-r","30","-c:v","libx264","-preset","veryfast","-crf","22","-c:a","aac","-b:a","160k","-movflags","+faststart",str(part)])
        parts.append(part)
    listing=work/"concat.txt"
    listing.write_text("".join("file '"+str(p).replace("'","'\\''")+"'\n" for p in parts),encoding="utf-8")
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(listing),"-c","copy","-movflags","+faststart",str(out)])
    return out

def worker(job_id, source, chat_path, ratio):
    jobdir=DATA/job_id
    try:
        with LOCK: JOBS[job_id]["status"]="analyzing"
        result=analyze(source,jobdir,chat_path)
        with LOCK: JOBS[job_id].update({"status":"rendering","analysis":result})
        output=render(source,result["clips"],jobdir/"BATATES_highlights.mp4",ratio)
        with LOCK: JOBS[job_id].update({"status":"complete","download":f"/jobs/{job_id}/download","filename":output.name})
    except Exception as e:
        with LOCK: JOBS[job_id].update({"status":"failed","error":str(e)[:1000]})

def new_job(source: Path, chat_path: Optional[Path], ratio: str):
    job_id=uuid.uuid4().hex[:12]
    with LOCK: JOBS[job_id]={"id":job_id,"status":"queued","created":__import__("time").time()}
    threading.Thread(target=worker,args=(job_id,source,chat_path,ratio),daemon=True).start()
    return {"job_id":job_id,"status":"queued","poll":f"/jobs/{job_id}"}

@app.get("/health")
def health():
    return {"ok":True,"service":"BATATES","features":{"upload":True,"direct_media_url":True,"chat_json":True,"optional_whisper":bool(os.getenv("BATATES_WHISPER_MODEL"))}}

@app.post("/jobs/upload")
async def upload_video(video: UploadFile=File(...), chat: Optional[UploadFile]=File(None), ratio: str=Form("9:16")):
    if ratio not in ("9:16","16:9"): raise HTTPException(400,"ratio must be 9:16 or 16:9")
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
    threading.Thread(target=worker,args=(job_id,source,chat_path,ratio),daemon=True).start()
    return {"job_id":job_id,"status":"queued","poll":f"/jobs/{job_id}"}

@app.post("/jobs/stream")
async def stream_url(url: str=Form(...), ratio: str=Form("9:16"), chat: Optional[UploadFile]=File(None)):
    # Accept direct, user-authorized media URLs only; platform pages/DRM/login bypass is not attempted.
    url=safe_url(url)
    if ratio not in ("9:16","16:9"): raise HTTPException(400,"ratio must be 9:16 or 16:9")
    job_id=uuid.uuid4().hex[:12]; jobdir=DATA/job_id; jobdir.mkdir(parents=True)
    source=jobdir/"stream_capture.mp4"
    chat_path=None
    if chat:
        chat_path=jobdir/"chat.json"
        chat_path.write_bytes(await chat.read())
    with LOCK: JOBS[job_id]={"id":job_id,"status":"capturing","created":__import__("time").time()}
    def capture():
        try:
            # Capture a bounded 10-minute segment; continuous live clipping requires a persistent stream worker.
            run(["ffmpeg","-y","-i",url,"-t","600","-c","copy",str(source)],timeout=660)
            with LOCK: JOBS[job_id]["status"]="queued"
            worker(job_id,source,chat_path,ratio)
        except Exception as e:
            with LOCK: JOBS[job_id].update({"status":"failed","error":str(e)[:1000]})
    threading.Thread(target=capture,daemon=True).start()
    return {"job_id":job_id,"status":"capturing","note":"Direct authorized media URL only; platform watch-page links may not work.","poll":f"/jobs/{job_id}"}

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
