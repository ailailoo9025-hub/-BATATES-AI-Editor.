"""Optional semantic video understanding through an OpenAI-compatible vision endpoint.
Set BATATES_VISION_API_KEY and BATATES_VISION_MODEL to enable it. No frames are sent
anywhere unless the operator explicitly configures an endpoint and key.
"""
import base64, json, os, re
from pathlib import Path
import cv2
import requests

def semantic_events(video: Path, duration: float, max_frames: int = 12):
    key=os.getenv("BATATES_VISION_API_KEY","").strip()
    model=os.getenv("BATATES_VISION_MODEL","").strip()
    if not key or not model:
        return {"enabled":False,"events":[],"reason":"Vision provider is not configured"}
    base=os.getenv("BATATES_VISION_BASE_URL","https://api.openai.com/v1").rstrip("/")
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return {"enabled":True,"events":[],"reason":"Could not decode video"}
    times=[(duration*i/(max_frames-1)) for i in range(max_frames)] if duration>0 and max_frames>1 else [0]
    content=[{"type":"text","text":"Analyze these timestamped frames from a creator video. Identify moments likely to make compelling short clips: visible reactions, surprising events, gameplay wins/fails, funny animal behavior, sports highlights, strong emotional moments, or clear scene actions. Do not infer events not visible. Return ONLY JSON: {\"events\":[{\"time\":seconds,\"title\":short title,\"reason\":short evidence-based reason,\"score\":0-100}]}."}]
    for sec in times:
        cap.set(cv2.CAP_PROP_POS_MSEC,sec*1000)
        ok,frame=cap.read()
        if not ok: continue
        frame=cv2.resize(frame,(512,288))
        ok,buf=cv2.imencode(".jpg",frame,[int(cv2.IMWRITE_JPEG_QUALITY),72])
        if not ok: continue
        data=base64.b64encode(buf.tobytes()).decode("ascii")
        content.append({"type":"text","text":f"Timestamp: {sec:.2f} seconds"})
        content.append({"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+data,"detail":"low"}})
    cap.release()
    if len(content)<3:
        return {"enabled":True,"events":[],"reason":"No frames could be sampled"}
    response=requests.post(base+"/chat/completions",headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},
      json={"model":model,"temperature":0.1,"messages":[{"role":"user","content":content}],"max_tokens":1200},timeout=90)
    response.raise_for_status()
    text=response.json()["choices"][0]["message"]["content"]
    text=re.sub(r"^\s*```(?:json)?|\`\`\`\s*$","",text.strip(),flags=re.I)
    data=json.loads(text)
    events=[]
    for item in data.get("events",[]):
        try:
            t=max(0,min(duration,float(item["time"])))
            events.append({"time":t,"title":str(item.get("title","Highlight"))[:100],
              "reason":str(item.get("reason",""))[:240],"score":max(0,min(100,float(item.get("score",50))))})
        except Exception: pass
    return {"enabled":True,"events":events,"frames_sent":len(content)//2}
