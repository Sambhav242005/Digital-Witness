"""Optional billable Gemini development smoke on generated geometric footage.

Run against the local server with LOAD_MODELS=true. This sends generated footage
to Google, not CCTV. It calibrates a synthetic development threshold only;
consenting staged footage and held-out acceptance are still required.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

import httpx
from PIL import Image, ImageDraw
from app.ai.gemini_embedding import GeminiEmbeddingAdapter
from app.config import Settings
from calibrate import calibrate


def terminal(client, key):
    deadline = time.monotonic()+300
    while time.monotonic()<deadline:
        response=client.get('/api/v1/jobs/'+key)
        response.raise_for_status()
        job=response.json()['data']
        if job['status']=='failed':
            raise RuntimeError(job['error']['code']+': '+job['error']['message'])
        if job['status']=='succeeded':
            return
        time.sleep(2)
    raise TimeoutError('Smoke job timed out')


def smoke(base_url, output):
    settings=Settings()
    directory=settings.data_dir/'live-smoke'
    directory.mkdir(parents=True,exist_ok=True)
    recordings=[]
    with httpx.Client(base_url=base_url,timeout=60) as client:
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            try:
                health=client.get('/api/v1/health').json()['data']
            except httpx.TransportError:
                time.sleep(2)
                continue
            if health['capabilities']['chat']:
                break
            time.sleep(2)
        else:
            raise TimeoutError('Gemini chat did not become available during startup')
        for shape in ('red_square','blue_circle'):
            image=Image.new('RGB',(320,240),'white')
            draw=ImageDraw.Draw(image)
            if shape=='red_square':
                draw.rectangle((80,40,240,200),fill='red')
            else:
                draw.ellipse((80,40,240,200),fill='blue')
            still=directory/(shape+'.png')
            image.save(still)
            source=directory/(shape+'.mp4')
            subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-loop','1','-i',str(still),'-t','4','-r','2','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(source)],check=True)
            start=time.perf_counter()
            with source.open('rb') as file:
                response=client.post('/api/v1/videos',files={'file':(source.name,file,'video/mp4')},data={'camera_label':'Synthetic '+shape})
            response.raise_for_status()
            accepted=response.json()['data']
            terminal(client,accepted['job']['job_id'])
            key=accepted['video']['video_id']
            prepared_sec=time.perf_counter()-start
            zones={'zones':[{'name':'Synthetic entrance','kind':'entrance','polygon':[{'x':.1,'y':.1},{'x':.9,'y':.1},{'x':.9,'y':.9},{'x':.1,'y':.9}]}]}
            response=client.put('/api/v1/videos/'+key+'/zones',json=zones)
            response.raise_for_status()
            start=time.perf_counter()
            response=client.post('/api/v1/videos/'+key+'/index',json={})
            response.raise_for_status()
            terminal(client,response.json()['data']['job']['job_id'])
            video=client.get('/api/v1/videos/'+key).json()['data']
            assert video['status']=='ready' and video['zones']
            part=client.get(video['playback_url'],headers={'Range':'bytes=0-1023'})
            assert part.status_code==206 and len(part.content)==1024
            recordings.append({'shape':shape,'video_id':key,'preparation_sec':prepared_sec,'indexing_sec':time.perf_counter()-start,'duration_sec':video['duration_sec']})
            print(shape+': real upload, prepare, zones, index, Range passed',flush=True)
    ids=[v['video_id'] for v in recordings]
    dataset={'queries':[
        {'query':'a red square on a white background','video_ids':ids,'expected':[{'video_id':ids[0],'start_sec':0,'end_sec':4}]},
        {'query':'a blue circle on a white background','video_ids':ids,'expected':[{'video_id':ids[1],'start_sec':0,'end_sec':4}]},
        {'query':'a person carrying a bag near the entrance','video_ids':ids,'expected':[]},
    ]}
    adapter=GeminiEmbeddingAdapter()
    try:
        adapter.load()
        outcome=calibrate(dataset,adapter,settings)
    finally:
        adapter.close()
    report={'scope':'Synthetic geometric development footage; not CCTV acceptance','recordings':recordings,'calibration':outcome,'labels':dataset}
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('Synthetic threshold:',outcome['relevance_threshold'],'development clip F1:',outcome['development_clip_f1'],flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://localhost:8000')
    parser.add_argument('--output',type=Path,default=Path('backend/data/live-smoke-report.json'))
    args=parser.parse_args()
    smoke(args.base_url,args.output)
