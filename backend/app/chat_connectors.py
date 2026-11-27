"""Official-platform chat collectors. Credentials are supplied by the server operator.
Twitch uses read-only IRC; YouTube uses the official Data API liveChatMessages endpoint.
"""
import os, re, threading, time
from datetime import datetime, timezone
import requests

class ChatCollector:
    def __init__(self):
        self.stop_event=threading.Event()
        self.rows=[]
        self.thread=None
        self.error=None
    def start(self, platform, stream_id):
        if platform=="twitch":
            self.thread=threading.Thread(target=self._twitch,args=(stream_id,),daemon=True)
        elif platform=="youtube":
            self.thread=threading.Thread(target=self._youtube,args=(stream_id,),daemon=True)
        else:
            raise ValueError("platform must be twitch or youtube")
        self.thread.start()
    def stop(self):
        self.stop_event.set()
    def _append(self, text):
        self.rows.append({"timestamp":time.time(),"text":str(text)[:500]})
        if len(self.rows)>20000: self.rows=self.rows[-20000:]
    def _twitch(self, channel):
        try:
            import websocket
            ws=websocket.create_connection("wss://irc-ws.chat.twitch.tv:443",timeout=20)
            ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
            ws.send("PASS SCHMOOPIIE\r\n")
            ws.send("NICK justinfan"+str(int(time.time())%99999)+"\r\n")
            ws.send("JOIN #"+channel.lstrip("#").lower()+"\r\n")
            ws.settimeout(2)
            while not self.stop_event.is_set():
                try: msg=ws.recv()
                except websocket.WebSocketTimeoutException: continue
                if msg.startswith("PING"): ws.send("PONG :tmi.twitch.tv\r\n"); continue
                if " PRIVMSG " in msg:
                    self._append(msg.split(" PRIVMSG ",1)[1].split(" :",1)[-1])
            ws.close()
        except Exception as e: self.error=str(e)
    def _youtube(self, video_id):
        try:
            key=os.getenv("BATATES_YOUTUBE_API_KEY","").strip()
            if not key: raise RuntimeError("Set BATATES_YOUTUBE_API_KEY to enable YouTube live chat.")
            base="https://www.googleapis.com/youtube/v3/"
            r=requests.get(base+"videos",params={"part":"liveStreamingDetails","id":video_id,"key":key},timeout=20); r.raise_for_status()
            items=r.json().get("items",[])
            live_id=(items[0].get("liveStreamingDetails",{}).get("activeLiveChatId") if items else None)
            if not live_id: raise RuntimeError("No active YouTube live chat found for this video.")
            token=None
            while not self.stop_event.is_set():
                params={"liveChatId":live_id,"part":"snippet,authorDetails","maxResults":200,"key":key}
                if token: params["pageToken"]=token
                r=requests.get(base+"liveChat/messages",params=params,timeout=20); r.raise_for_status()
                data=r.json()
                for item in data.get("items",[]):
                    snippet=item.get("snippet",{})
                    self._append(snippet.get("displayMessage",""))
                token=data.get("nextPageToken")
                delay=max(1,int(data.get("pollingIntervalMillis",5000))/1000)
                self.stop_event.wait(delay)
        except Exception as e: self.error=str(e)
