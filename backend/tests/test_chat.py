import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from app.config import Settings
from app.main import create_app
from app.schemas import Chat
from app.chat import GeminiChatAdapter, declarations, FinishTool
from app.ai import ModelUnavailable
from test_api import TestEmbedding, MissingVerification, ready


def call(name, args):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model',parts=[types.Part(function_call=types.FunctionCall(name=name,args=args,id='tool-call-id'),thought_signature=b'signature')]))])


class ChatModel:
    available = True
    def step(self, contents):
        last = contents[-1].parts[0]
        if last.function_response is None:
            initial = json.loads(last.text)
            message = initial['messages'][-1]['text']
            if message == 'Only show matches after 2 minutes.':
                return call('search_video',{'time_range':{'start_sec':120,'end_sec':initial['recordings'][0]['duration_sec']}})
            return call('search_video',{'query':'person carrying a bag'})
        response = last.function_response
        assert response.id == 'tool-call-id'
        if response.name == 'search_video':
            return call('get_search_results',{'search_id':response.response['data']['search_id']})
        if response.name == 'get_search_results':
            search = response.response['data']
            return call('finish_response',{'reason':'results_found' if search['results'] else 'no_results','result_ids':[r['result_id'] for r in search['results'][:2]]})
        raise AssertionError('Unexpected function response')


@pytest.fixture
def chat_client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path,worker_enabled=False,relevance_threshold=.5),TestEmbedding(),MissingVerification(),ChatModel())
    with TestClient(app) as client:
        yield client


@pytest.fixture
def long_footage(tmp_path):
    path = tmp_path/'long.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=1','-t','130','-c:v','libx264','-threads','1','-y',str(path)],check=True)
    return path.read_bytes()


def new_chat(client, video):
    response = client.post('/api/v1/chats',json={'video_ids':[video['video_id']]})
    assert response.status_code==201, response.text
    return response.json()['data']['chat_id']


def turn(client, key, message):
    response = client.post('/api/v1/chats/'+key+'/messages',json={'message':message})
    assert response.status_code==202, response.text
    assert client.get('/api/v1/chats/'+key).json()['data']['status']=='running'
    client.app.state.service.run_one()
    chat = client.get('/api/v1/chats/'+key).json()['data']
    Chat.model_validate(chat)
    assert chat['status']=='idle',chat
    return chat


def test_chat_followup_preserves_query_and_applies_minutes_filter(chat_client,long_footage):
    video = ready(chat_client,long_footage)
    key = new_chat(chat_client,video)
    first = turn(chat_client,key,'Find someone carrying a bag near the entrance.')
    assert first['messages'][-1]['result_ids']
    assert first['messages'][-1]['search_ids']
    assert 'Not checked:' in first['messages'][-1]['text']
    assert first['messages'][-1]['text'].count('Frame verification is unavailable.') == 1
    assert 'result_' not in first['messages'][-1]['text']
    assert 'person carrying a bag' in first['messages'][-1]['text']
    assert first['context']['query']=='person carrying a bag'
    second = turn(chat_client,key,'Only show matches after 2 minutes.')
    assert second['context']['query']==first['context']['query']
    assert second['context']['video_ids']==[video['video_id']]
    assert second['context']['time_range']=={'start_sec':120.0,'end_sec':130.0}
    search = chat_client.get('/api/v1/searches/'+second['messages'][-1]['search_ids'][0]).json()['data']
    assert search['results'] and all(r['end_sec']>120 for r in search['results'])


def test_chat_duplicate_message_rejected_and_restart_failed(chat_client,long_footage):
    key = new_chat(chat_client,ready(chat_client,long_footage))
    url = '/api/v1/chats/'+key+'/messages'
    assert chat_client.post(url,json={'message':'bag'}).status_code==202
    assert chat_client.post(url,json={'message':'bag'}).status_code==409
    chat_client.app.state.service.store.recover()
    chat = chat_client.get('/api/v1/chats/'+key).json()['data']
    assert chat['status']=='failed' and chat['active_turn_id'] is None
    assert chat['error']['code']=='WORKER_INTERRUPTED'
    assert len(chat['messages'])==1


def test_chat_rejects_invented_evidence_without_publishing_claim(chat_client,long_footage):
    class HallucinatingModel:
        available=True
        def step(self,contents):
            return call('finish_response',{'reason':'results_found','result_ids':['invented']})
    key = new_chat(chat_client,ready(chat_client,long_footage))
    chat_client.app.state.service.chat.adapter=HallucinatingModel()
    chat_client.post('/api/v1/chats/'+key+'/messages',json={'message':'bag'})
    chat_client.app.state.service.run_one()
    chat = chat_client.get('/api/v1/chats/'+key).json()['data']
    assert chat['status']=='failed'
    assert not any(m['role']=='assistant' for m in chat['messages'])


def test_chat_scope_rejects_unselected_recording(chat_client,long_footage):
    first=ready(chat_client,long_footage)
    second=ready(chat_client,long_footage)
    class ScopeModel:
        available=True
        def step(self,contents):
            if contents[-1].parts[0].function_response:
                response=contents[-1].parts[0].function_response.response
                assert response['error']['code']=='VALIDATION_ERROR'
                return call('finish_response',{'reason':'processing_failed'})
            return call('search_video',{'query':'bag','video_ids':[second['video_id']]})
    key=new_chat(chat_client,first)
    chat_client.app.state.service.chat.adapter=ScopeModel()
    chat=turn(chat_client,key,'Find a bag')
    assert 'must belong to this chat' in chat['messages'][-1]['text']
    with chat_client.app.state.service.store.transaction() as db:
        assert chat_client.app.state.service.store.all(db,'search')==[]


def test_chat_missing_resource_and_missing_model(chat_client,long_footage):
    response=chat_client.get('/api/v1/chats/missing')
    assert response.status_code==404 and response.json()['error']['code']=='CHAT_NOT_FOUND'
    video=ready(chat_client,long_footage)
    chat_client.app.state.service.chat.adapter.available=False
    assert chat_client.post('/api/v1/chats',json={'video_ids':[video['video_id']]}).status_code==503


def test_chat_sdk_types_and_smoke_gate(monkeypatch):
    tool=declarations()
    assert {f.name for f in tool.function_declarations}=={'search_video','get_search_results','inspect_frames','finish_response'}
    fake=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs:call('finish_response',{'reason':'needs_input','clarification':'query'})))
    adapter=GeminiChatAdapter(client=fake)
    assert not adapter.available
    adapter.load()
    assert adapter.available
    fake.models.generate_content=lambda **kwargs:types.GenerateContentResponse()
    with pytest.raises(ModelUnavailable):
        adapter.load()
    assert not adapter.available


def test_no_results_reply_cannot_use_earlier_empty_search(chat_client):
    empty=types.Part.from_function_response(name='get_search_results',response={'data':{'search_id':'old','status':'succeeded','results':[]}})
    matched=types.Part.from_function_response(name='get_search_results',response={'data':{'search_id':'new','status':'succeeded','results':[{'result_id':'match'}]}})
    contents=[types.Content(role='user',parts=[empty]),types.Content(role='user',parts=[matched])]
    with pytest.raises(ValueError):
        chat_client.app.state.service.chat.render(FinishTool(reason='no_results'),{'match':{}},contents,['old','new'],[])


def test_chat_history_survives_new_server(tmp_path,long_footage):
    settings=Settings(data_dir=tmp_path,worker_enabled=False,relevance_threshold=.5)
    with TestClient(create_app(settings,TestEmbedding(),MissingVerification(),ChatModel())) as client:
        key=new_chat(client,ready(client,long_footage))
        chat=turn(client,key,'bag')
    with TestClient(create_app(settings,TestEmbedding(),MissingVerification(),ChatModel())) as client:
        restored=client.get('/api/v1/chats/'+key).json()['data']
        assert restored['messages']==chat['messages']
        assert restored['context']==chat['context']
