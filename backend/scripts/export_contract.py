"""Export actual FastAPI OpenAPI and schema-validated integration fixtures."""
import json
from pathlib import Path
from app.schemas import Data, ErrorEnvelope, Health, Job, Search, SearchAccepted, Video, VideoJob, VideoList, EmptyRequest, SearchRequest, ZoneRequest, Chat, ChatCreateRequest, ChatMessageRequest, ChatTurnAccepted

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'contracts'
STAMP = '2026-10-08T04:30:00Z'
BASE = 'http://localhost:8000/api/v1/media/'


def export(app):
    OUT.mkdir(exist_ok=True)
    (OUT / 'openapi.json').write_text(json.dumps(app.openapi(), indent=2) + '\n')
    fixtures = OUT / 'fixtures'
    fixtures.mkdir(exist_ok=True)
    def save(name, model, value):
        validated = model.model_validate(value)
        (fixtures / f'{name}.json').write_text(validated.model_dump_json(indent=2) + '\n')
    error = {'code':'INDEXING_FAILED','message':'Indexing failed; retry the recording.','details':{}}
    video = dict(video_id='vid_fixture', filename='fixture.mp4', camera_label='Fixture Camera', status='draft', created_at=STAMP, duration_sec=12.0, width=320, height=240, playback_url=BASE+'media_fixture_video', thumbnail_url=BASE+'media_fixture_thumb', zones=[], active_job_id=None,error=None)
    job = dict(job_id='job_fixture',kind='prepare_video',resource_id='vid_fixture',status='queued',stage='queued',progress_pct=0,created_at=STAMP,updated_at=STAMP,error=None)
    save('health_live',Data[Health],{'data':dict(status='ok',contract_version='1.1',mode='live',capabilities=dict(semantic_search=False,chat=False,frame_verification=False,temporal_events=False),supported_event_types=[])})
    for state in ['preparing','draft','indexing','ready','failed']:
        item = dict(video,status=state)
        if state in ('preparing','indexing'):
            item['active_job_id']='job_fixture'
        if state == 'preparing':
            for key in ('duration_sec','width','height','playback_url','thumbnail_url'):
                item[key]=None
        if state == 'failed':
            item['error']=error
        save('video_'+state,Data[Video],{'data':item})
    failed_prepare = dict(video,status='failed',error=dict(code='MEDIA_DECODE_FAILED',message='The recording could not be decoded.',details={}))
    for key in ('duration_sec','width','height','playback_url','thumbnail_url'):
        failed_prepare[key]=None
    save('video_failed_preparation',Data[Video],{'data':failed_prepare})
    save('video_failed_indexing',Data[Video],{'data':dict(video,status='failed',error=error)})
    save('video_with_zone',Data[Video],{'data':dict(video,zones=[dict(zone_id='zone_fixture',name='Entrance',kind='entrance',polygon=[dict(x=.1,y=.1),dict(x=.9,y=.1),dict(x=.9,y=.9),dict(x=.1,y=.9)])])})
    save('videos_list',Data[VideoList],{'data':dict(items=[video],total=1,limit=20,offset=0)})
    for status,stage,pct in [('queued','queued',0),('running','preparing',45),('succeeded','complete',100),('failed','failed',45)]:
        save('job_'+status,Data[Job],{'data':dict(job,status=status,stage=stage,progress_pct=pct,error=error if status=='failed' else None)})
    for name,kind,status in [('upload_accepted','prepare_video','preparing'),('index_accepted','index_video','indexing'),('retry_accepted','index_video','indexing')]:
        accepted_video = dict(video,status=status,active_job_id='job_fixture')
        if status == 'preparing':
            for key in ('duration_sec','width','height','playback_url','thumbnail_url'):
                accepted_video[key] = None
        save(name,Data[VideoJob],{'data':dict(video=accepted_video,job=dict(job,kind=kind))})
    save('request_search',SearchRequest,dict(query='person carrying a bag',video_ids=['vid_fixture'],limit=10,time_range=dict(start_sec=0,end_sec=12),event_types=[]))
    save('request_zones',ZoneRequest,dict(zones=[dict(name='Entrance',kind='entrance',polygon=[dict(x=.1,y=.1),dict(x=.9,y=.1),dict(x=.9,y=.9),dict(x=.1,y=.9)])]))
    save('request_clear_zones',ZoneRequest,dict(zones=[]))
    save('request_index',EmptyRequest,{})
    save('request_retry',EmptyRequest,{})
    search = dict(search_id='search_fixture',job_id='job_fixture_search',status='queued',query='person carrying a bag',video_ids=['vid_fixture'],created_at=STAMP,warnings=[],results=[],error=None)
    save('search_accepted',Data[SearchAccepted],{'data':dict(search_id='search_fixture',job=dict(job,job_id='job_fixture_search',kind='search',resource_id='search_fixture'))})
    for status in ['queued','running','succeeded','failed']:
        save('search_'+status,Data[Search],{'data':dict(search,status=status,error=dict(code='SEARCH_FAILED',message='Search failed; submit a new search.',details={}) if status=='failed' else None)})
    result = dict(result_id='result_fixture',video_id='vid_fixture',camera_label='Fixture Camera',start_sec=0,end_sec=8,thumbnail_url=BASE+'media_fixture_thumb',playback_url=BASE+'media_fixture_video',summary='Illustrative candidate fixture; no measured model result.',event_type=None,zone_id=None,retrieval_score=.72,verification=dict(status='not_checked',reason='Illustrative fixture.',basis='none'),evidence=[])
    for status in ['supported','uncertain','contradicted','not_checked']:
        checked = status != 'not_checked'
        item = dict(result,verification=dict(status=status,reason='Illustrative frame-check fixture; temporal actions are unverified.',basis='frame_checks' if checked else 'none'),evidence=[dict(timestamp_sec=4,image_url=BASE+'media_fixture_thumb',quality='poor' if status=='uncertain' else 'usable',checks=[dict(check_id='person_carrying_bag',question='Is a person visibly carrying a bag?',answer='yes' if status=='supported' else 'no' if status=='contradicted' else 'uncertain',probability_yes=None)])] if checked else [])
        warnings=[dict(code='VERIFICATION_UNAVAILABLE',message='Frame verification is unavailable.')] if not checked else []
        save('search_results_'+status,Data[Search],{'data':dict(search,status='succeeded',results=[item],warnings=warnings)})
    for code in ['VIDEO_NOT_FOUND','JOB_NOT_FOUND','SEARCH_NOT_FOUND','CHAT_NOT_FOUND','MEDIA_NOT_FOUND','VIDEO_NOT_READY','INVALID_STATE','JOB_ALREADY_RUNNING','FILE_TOO_LARGE','UNSUPPORTED_MEDIA_TYPE','VALIDATION_ERROR','INVALID_ZONE','UNSUPPORTED_EVENT_TYPE','QUEUE_FULL','MODEL_UNAVAILABLE','INTERNAL_ERROR']:
        save('error_'+code.lower(),ErrorEnvelope,dict(error=dict(code=code,message=code.replace('_',' ').capitalize(),details={}),request_id='req_fixture'))
    save('request_chat_create',ChatCreateRequest,dict(video_ids=['vid_fixture']))
    save('request_chat_message',ChatMessageRequest,dict(message='Show a person carrying a bag'))
    chat = dict(chat_id='chat_fixture',video_ids=['vid_fixture'],created_at=STAMP,updated_at=STAMP,status='idle',active_turn_id=None,context=None,messages=[],error=None)
    save('chat_created',Data[Chat],{'data':chat})
    for status in ['idle','running','failed']:
        save('chat_'+status,Data[Chat],{'data':dict(chat,status=status,active_turn_id='turn_fixture' if status=='running' else None,context=dict(query='person carrying a bag',video_ids=['vid_fixture'],limit=10,time_range=None,event_types=[]),messages=[dict(message_id='message_fixture',role='user',text='Show a person carrying a bag',created_at=STAMP,search_ids=[],result_ids=[])],error=dict(code='WORKER_INTERRUPTED',message='The turn was interrupted; submit another message.',details={}) if status=='failed' else None)})
    save('chat_turn_accepted',Data[ChatTurnAccepted],{'data':dict(chat_id='chat_fixture',turn_id='turn_fixture')})
    (fixtures/'README.md').write_text('These examples are illustrative contract fixtures, not measured model outputs. Run the fixture media seeding command documented in README before opening localhost media URLs. The ready fixture refers to vid_fixture; media IDs are media_fixture_video and media_fixture_thumb.\n')

if __name__ == '__main__':
    from app.main import app
    export(app)
