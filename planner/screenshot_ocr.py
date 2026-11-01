"""WeMust-style colored week screenshot candidates; never silently import guesses."""
import hashlib,re,threading
from datetime import timedelta
from pathlib import Path
import numpy as np
import cv2
_engine=None
_lock=threading.Lock()
def recognize(image,monday):
    global _engine
    from rapidocr import RapidOCR
    # A single local engine avoids concurrent model initialization.
    with _lock:
        if _engine is None:_engine=RapidOCR()
        a=np.asarray(image);h,w=a.shape[:2]
        # Bound inference size while keeping column text legible.
        if w>1600:a=cv2.resize(a,(1600,round(h*1600/w)));h,w=a.shape[:2]
        result=_engine(a,use_cls=False)
    texts=result.txts or [];boxes=result.boxes if result.boxes is not None else []
    raw='\n'.join(texts)
    hsv=cv2.cvtColor(a,cv2.COLOR_RGB2HSV)
    mask=cv2.inRange(hsv,np.array([0,12,160]),np.array([179,255,255]))
    mask[:int(h*.12)]=0;mask[:,:int(w*.10)]=0
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((9,5),np.uint8))
    # Split neighboring colored cards at weekday boundaries before finding regions.
    weekday_centers=[]; grid=[]
    for text,box in zip(texts,boxes):
        center=np.asarray(box).mean(axis=0)
        if re.search('[周週][一二三四五六日]',text):weekday_centers.append(float(center[0]))
        m=re.fullmatch(r'(\d{1,2})[:：](\d{2})',text.strip())
        if m and center[0]<w*.11 and int(m[1])<=24:grid.append((float(center[1]),int(m[1])*60+int(m[2])))
    weekday_centers.sort()
    for left,right in zip(weekday_centers,weekday_centers[1:]):
        boundary=round((left+right)/2);mask[:,boundary-2:boundary+3]=0
    fit=np.polyfit([g[0] for g in grid],[g[1] for g in grid],1) if len(grid)>=5 else None
    def grid_time(y):
        if fit is None:return ''
        minute=max(0,min(1439,round(float(np.polyval(fit,y))/5)*5))
        return f'{minute//60:02}:{minute%60:02}'
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    rects=[]
    for contour in contours:
        x,y,cw,ch=cv2.boundingRect(contour)
        if .045*w<cw<.23*w and ch>.025*h and cw*ch>.0015*w*h:rects.append((x,y,cw,ch))
    rects.sort(key=lambda r:(r[0],r[1]));rows=[]
    digest=hashlib.sha256(a.tobytes()).hexdigest()[:16]
    anchors=[]
    names=['一','二','三','四','五','六','日']
    for text,box in zip(texts,boxes):
        for i,n in enumerate(names):
            if re.search('[周週]'+n,text):anchors.append((i,float(np.mean(np.asarray(box)[:,0]))))
    for index,(x,y,cw,ch) in enumerate(rects[:30]):
        parts=[]
        for text,box in zip(texts,boxes):
            center=np.asarray(box).mean(axis=0)
            if x-5<=center[0]<=x+cw+5 and y-5<=center[1]<=y+ch+5:parts.append((center[1],text))
        parts.sort();text=' '.join(p[1] for p in parts)
        if not text:continue
        day=min(anchors,key=lambda p:abs(p[1]-(x+cw/2)))[0] if len(anchors)>=5 else max(0,min(6,int((x+cw/2-w*.11)/(w*.89/7))))
        times=re.findall(r'([0-2]?\d)[:：]([0-5]\d)',text)
        ts=[f'{int(hour):02}:{minute}' for hour,minute in times if int(hour)<24]
        # Teacher and room often wrap across lines: leave them for explicit review.
        title=re.split(r'[@＠]|課室|课室|\d{1,2}[:：]\d{2}',text)[0].strip()[:100]
        title=re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fffA-Za-z])','',title) or '待校对课程'
        room_match=re.search(r'(?<![A-Za-z])[BCDF][0-9][0-9\s]{1,5}',text)
        room=re.sub(r'\s+','',room_match[0]) if room_match else ''
        rows.append(dict(source_key='ocr-'+digest+'-'+str(index),course_code='OCR-'+hashlib.sha256(title.encode()).hexdigest()[:8],course_title=title,date=(monday+timedelta(days=day)).isoformat(),start_time=ts[0] if len(ts)>1 else grid_time(y),end_time=ts[1] if len(ts)>1 else grid_time(y+ch),room=room,teacher='',approx_time=len(ts)<2))
    if not rows:rows=[dict(source_key='ocr-'+digest+'-0',course_code='',course_title='',date=monday.isoformat(),start_time='',end_time='',room='',teacher='')]
    return rows,raw
