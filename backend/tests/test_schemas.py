import pytest
from pydantic import ValidationError
from app.schemas import EmptyRequest, Point, SearchRequest, Video, ZoneRequest


def zone(points):
    return {'zones': [{'name': ' Entrance ', 'kind': 'entrance', 'polygon': [{'x':x,'y':y} for x,y in points]}]}


def test_request_defaults_and_trim():
    value = SearchRequest(query='  bag  ', video_ids=['opaque'])
    assert value.query == 'bag'
    assert value.limit == 10
    assert value.event_types == []
    assert ZoneRequest.model_validate(zone([(0,0),(1,0),(1,1),(0,1)])).zones[0].name == 'Entrance'
    assert ZoneRequest(zones=[]).zones == []


@pytest.mark.parametrize('body', [
    {'query':' ', 'video_ids':['a']},
    {'query':'bag', 'video_ids':[]},
    {'query':'bag', 'video_ids':['a','a']},
    {'query':'bag', 'video_ids':['a'], 'limit':51},
    {'query':'bag', 'video_ids':['a','b'], 'time_range':{'start_sec':0,'end_sec':1}},
    {'query':'bag', 'video_ids':['a'], 'time_range':{'start_sec':1,'end_sec':1}},
    {'query':'bag', 'video_ids':['a'], 'time_range':{'start_sec':0,'end_sec':float('inf')}},
    {'query':'bag', 'video_ids':['a'], 'event_types':['unknown']},
])
def test_invalid_search(body):
    with pytest.raises(ValidationError):
        SearchRequest.model_validate(body)


@pytest.mark.parametrize('points', [
    [(0,0),(1,1),(0,1),(1,0)],
    [(0,0),(1,0),(0,0)],
    [(0,0),(.5,.5),(1,1)],
    [(0,0),(1,0),(.5,0),(.5,1),(0,1)],
    [(0,0),(1,0),(1,1),(.5,0),(0,1)],
])
def test_invalid_polygons(points):
    with pytest.raises(ValidationError):
        ZoneRequest.model_validate(zone(points))


def test_collinear_continuation_is_simple():
    ZoneRequest.model_validate(zone([(0,0),(.5,0),(1,0),(1,1),(0,1)]))


def test_output_nulls_are_required():
    props = Video.model_json_schema()
    assert 'duration_sec' in props['required']
    assert 'error' in props['required']
    assert 'active_job_id' in props['required']
    with pytest.raises(ValidationError):
        EmptyRequest.model_validate({'surprise':True})
    with pytest.raises(ValidationError):
        Point(x=float('nan'), y=0)


def test_output_envelope_required_fields():
    from app.schemas import ApiError, Data, Health
    with pytest.raises(ValidationError):
        ApiError(code='X', message='Error')
    health = Data[Health].model_validate({'data': {'status':'ok','contract_version':'1.1','mode':'live','capabilities':{'semantic_search':False,'chat':False,'frame_verification':False,'temporal_events':False},'supported_event_types':[]}})
    assert health.model_dump()['data']['supported_event_types'] == []


def test_contract_fixtures_validate():
    import json
    from pathlib import Path
    from app.schemas import Data, ErrorEnvelope, Health, Job, Search, SearchAccepted, VideoJob, VideoList, Chat, ChatCreateRequest, ChatMessageRequest, ChatTurnAccepted
    directory = Path(__file__).resolve().parents[2] / 'contracts' / 'fixtures'
    for path in directory.glob('*.json'):
        name = path.stem
        if name.startswith('error_'):
            model = ErrorEnvelope
        elif name == 'request_chat_create':
            model = ChatCreateRequest
        elif name == 'request_chat_message':
            model = ChatMessageRequest
        elif name == 'chat_turn_accepted':
            model = Data[ChatTurnAccepted]
        elif name.startswith('chat_'):
            model = Data[Chat]
        elif name == 'request_search':
            model = SearchRequest
        elif name in ('request_zones','request_clear_zones'):
            model = ZoneRequest
        elif name in ('request_index','request_retry'):
            model = EmptyRequest
        elif name.startswith('health_'):
            model = Data[Health]
        elif name == 'videos_list':
            model = Data[VideoList]
        elif name in ('upload_accepted','index_accepted','retry_accepted'):
            model = Data[VideoJob]
        elif name.startswith('video_'):
            model = Data[Video]
        elif name.startswith('job_'):
            model = Data[Job]
        elif name == 'search_accepted':
            model = Data[SearchAccepted]
        else:
            model = Data[Search]
        model.model_validate(json.loads(path.read_text()))
    uploaded = json.loads((directory / 'upload_accepted.json').read_text())['data']['video']
    assert uploaded['playback_url'] is None
    assert uploaded['duration_sec'] is None


def test_generated_openapi_uses_canonical_envelopes():
    import json
    from pathlib import Path
    spec = json.loads((Path(__file__).resolve().parents[2] / 'contracts' / 'openapi.json').read_text())
    for path, operations in spec['paths'].items():
        for method, operation in operations.items():
            if method not in ('get','post','put'):
                continue
            for code, response in operation['responses'].items():
                if int(code) >= 400 and code != '416':
                    assert response['content']['application/json']['schema']['$ref'].endswith('/ErrorEnvelope')
                elif int(code) < 300 and '/media/' not in path:
                    ref = response['content']['application/json']['schema']['$ref']
                    schema = spec['components']['schemas'][ref.split('/')[-1]]
                    assert schema['required'] == ['data']
    assert 'HTTPValidationError' not in spec['components']['schemas']


@pytest.mark.parametrize('ids', [[], ['a','a'], [''], ['a']*21])
def test_chat_create_rejects_bad_ids(ids):
    from app.schemas import ChatCreateRequest
    with pytest.raises(ValidationError):
        ChatCreateRequest(video_ids=ids)


def test_chat_message_validation():
    from app.schemas import ChatMessageRequest
    assert ChatMessageRequest(message='  hello  ').message == 'hello'
    for value in (' ', 'a'*2001):
        with pytest.raises(ValidationError):
            ChatMessageRequest(message=value)



def test_selected_gemini_frame_fixture_has_no_probability():
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / 'contracts' / 'fixtures' / 'search_results_supported.json'
    value = json.loads(path.read_text())
    assert value['data']['results'][0]['evidence'][0]['checks'][0]['probability_yes'] is None
