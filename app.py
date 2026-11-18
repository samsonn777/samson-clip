from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import shutil, subprocess, uuid, json, re

ROOT=Path(__file__).parent
UPLOADS=ROOT/'uploads'; OUTPUTS=ROOT/'outputs'
UPLOADS.mkdir(exist_ok=True); OUTPUTS.mkdir(exist_ok=True)
app=FastAPI(title='Samson Clip')
app.mount('/static', StaticFiles(directory=ROOT/'static'), name='static')

@app.get('/', response_class=HTMLResponse)
def home(): return (ROOT/'templates'/'index.html').read_text()

@app.post('/api/process')
async def process(video: UploadFile=File(None), source_url: str=Form(''), clip_count: int=Form(5), duration: int=Form(45)):
    if not video and not source_url.strip(): raise HTTPException(400,'Upload a video to get started.')
    if source_url.strip():
        # Intentionally accept only direct media URLs. YouTube pages require authorized access / user-provided files.
        if not re.match(r'^https?://',source_url): raise HTTPException(400,'Enter a valid URL.')
        raise HTTPException(400,'For YouTube videos, upload a copy you own or have permission to use. Direct media URL importing can be added for authorized sources.')
    ext=Path(video.filename or 'video.mp4').suffix.lower()
    if ext not in ['.mp4','.mov','.mkv','.webm','.m4v']: raise HTTPException(400,'Please upload MP4, MOV, MKV or WebM.')
    job=uuid.uuid4().hex[:10]; src=UPLOADS/f'{job}{ext}';
    with src.open('wb') as f: shutil.copyfileobj(video.file,f)
    try:
        probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(src)],capture_output=True,text=True,check=True)
        total=float(probe.stdout.strip())
    except Exception: src.unlink(missing_ok=True); raise HTTPException(400,'Could not read this video. Check that FFmpeg is installed and the file is valid.')
    count=max(1,min(int(clip_count),12)); length=max(15,min(int(duration),90));
    # Evenly spaced highlights provide a reliable first-pass MVP. Add Whisper/LLM ranking in a production deployment.
    actual=min(length,total); starts=[]
    if total <= actual: starts=[0]
    else:
        count=min(count,max(1,int(total//actual)))
        starts=[(total-actual)*i/max(1,count-1) for i in range(count)]
    clips=[]
    for i,start in enumerate(starts,1):
        out=OUTPUTS/f'{job}_{i}.mp4'
        vf="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        cmd=['ffmpeg','-y','-ss',str(start),'-i',str(src),'-t',str(actual),'-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','23','-c:a','aac','-b:a','128k','-movflags','+faststart',str(out)]
        run=subprocess.run(cmd,capture_output=True,text=True)
        if run.returncode==0: clips.append({'name':f'Clip {i}','start':round(start),'duration':round(actual),'url':f'/api/download/{out.name}'})
    src.unlink(missing_ok=True)
    if not clips: raise HTTPException(500,'Video conversion failed. Check FFmpeg installation.')
    return {'job_id':job,'clips':clips,'note':'First-pass clips are spaced across the video. AI moment ranking and animated captions are planned upgrades.'}

@app.get('/api/download/{filename}')
def download(filename:str):
    path=(OUTPUTS/Path(filename).name)
    if not path.exists(): raise HTTPException(404,'Clip not found')
    return FileResponse(path,media_type='video/mp4',filename=path.name)
