import asyncio
from pathlib import Path
import subprocess

import pytest

from app.media import MediaError, frame, media_response, prepare, windows


def body(response):
    async def consume():
        return b''.join([chunk async for chunk in response.body_iterator])
    return asyncio.run(consume())


@pytest.mark.parametrize('range_header,status,expected', [(None,200,b'0123456789'),('bytes=2-4',206,b'234'),('bytes=7-',206,b'789'),('bytes=-3',206,b'789'),('bytes=3-99',206,b'3456789')])
def test_range(tmp_path, range_header, status, expected):
    path = tmp_path/'bytes'
    path.write_bytes(b'0123456789')
    response = media_response(path,'video/mp4',range_header)
    assert response.status_code == status
    assert response.headers['accept-ranges'] == 'bytes'
    assert int(response.headers['content-length']) == len(expected)
    assert body(response) == expected


@pytest.mark.parametrize('range_header',['bytes=10-','bytes=6-3','bytes=-0','bytes=0-1,4-5','bad'])
def test_invalid_range(tmp_path,range_header):
    path=tmp_path/'bytes'
    path.write_bytes(b'0123456789')
    response=media_response(path,'video/mp4',range_header)
    assert response.status_code==416
    assert response.headers['content-range']=='bytes */10'


def test_windows():
    assert windows(10)==[(0,8),(4,10),(8,10)]
    assert windows(2)==[(0,2)]


def test_real_prepare_and_frame(tmp_path):
    source=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-t','2','-c:v','mpeg4',str(source)],check=True)
    result=prepare(source,tmp_path/'prepared')
    assert result['duration_sec']==pytest.approx(2)
    assert (result['width'],result['height'])==(160,90)
    assert result['thumbnail_path'].stat().st_size>0
    assert frame(result['playback_path'],1.2,tmp_path/'frame.jpg').stat().st_size>0


def test_bad_content_sanitized(tmp_path):
    source=tmp_path/'private-name.mp4'
    source.write_text('invalid')
    with pytest.raises(MediaError) as error:
        prepare(source,tmp_path/'out')
    assert error.value.code=='MEDIA_DECODE_FAILED'
    assert str(source) not in error.value.message


def probe_frames(path):
    import json
    result=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(path)],capture_output=True,text=True,check=True)
    return [float(f['best_effort_timestamp_time']) for f in json.loads(result.stdout)['frames']]


def test_nonzero_origin_preserves_relative_frames(tmp_path):
    from app.media import _probe
    source=tmp_path/'offset.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-t','1','-c:v','libx264','-output_ts_offset','5',str(source)],check=True)
    assert float(_probe(source)['format']['start_time'])==5
    result=prepare(source,tmp_path/'out')
    expected=[t-5 for t in probe_frames(source)]
    assert probe_frames(result['playback_path'])==pytest.approx(expected,abs=0.001)
    assert result['duration_sec']==pytest.approx(1)


def test_rotation_uses_display_dimensions(tmp_path):
    from app.media import _probe
    base=tmp_path/'base.mp4'
    source=tmp_path/'rotated.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-t','1','-c:v','libx264',str(base)],check=True)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-display_rotation','90','-i',str(base),'-c','copy',str(source)],check=True)
    result=prepare(source,tmp_path/'out')
    assert (result['width'],result['height'])==(90,160)
    assert result['duration_sec']==float(_probe(result['playback_path'])['format']['duration'])


def test_vfr_gaps_preserved(tmp_path):
    source=tmp_path/'vfr.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-t','2','-vf',"select='not(mod(n,3))'",'-fps_mode','vfr','-c:v','libx264',str(source)],check=True)
    result=prepare(source,tmp_path/'out')
    assert probe_frames(result['playback_path'])==pytest.approx(probe_frames(source),abs=0.001)


def test_audio_tail_trimmed_to_video(tmp_path):
    from app.media import _probe
    source=tmp_path/'audio.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x90:rate=10:duration=1','-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-c:a','aac',str(source)],check=True)
    result=prepare(source,tmp_path/'out')
    assert result['duration_sec']==pytest.approx(1,abs=0.025)
    assert result['duration_sec']==float(_probe(result['playback_path'])['format']['duration'])
