"""Create synthetic local media for contract fixtures, separate from live recordings."""
from pathlib import Path
import subprocess

from app.config import Settings
from app.store import Store


def seed(settings=None):
    settings = settings or Settings()
    directory = settings.data_dir / 'fixture-media'
    directory.mkdir(parents=True, exist_ok=True)
    video = directory / 'fixture.mp4'
    thumbnail = directory / 'fixture.jpg'
    subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i','testsrc2=size=320x240:rate=10','-t','12','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],check=True)
    subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-ss','4','-i',str(video),'-frames:v','1',str(thumbnail)],check=True)
    store = Store(settings.data_dir)
    with store.transaction() as db:
        for key,path,content_type in [('media_fixture_video',video,'video/mp4'),('media_fixture_thumb',thumbnail,'image/jpeg')]:
            db.execute('INSERT INTO media VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET path=excluded.path,content_type=excluded.content_type', (key,str(path),content_type,'vid_fixture','fixture'))
    print('Fixture media ready at '+settings.public_base_url+'/api/v1/media/media_fixture_video')


if __name__ == '__main__':
    seed()
