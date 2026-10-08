from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.ai import ModelUnavailable
from app.ai import upstream
from app.ai.gemini_embedding import GeminiEmbeddingAdapter
from app.ai.gemini_verification import GeminiVerificationAdapter
from app.chat import GeminiChatAdapter
from app.main import create_app
from app.config import Settings
from test_api import TestEmbedding, MissingVerification, ready, footage
from test_chat import call

class ProviderError(Exception):
    def __init__(self, status, retry='3'):
        super().__init__('SECRET_KEY private footage raw SDK request')
        self.code = status
        self.response = SimpleNamespace(headers={'Retry-After':retry})

@pytest.mark.parametrize('status', [429,503])
@pytest.mark.parametrize('kind', ['chat','embedding','vision'])
def test_provider_failure_sanitized_cooldown_recovery(monkeypatch,status,kind):
    clock=[100.0]
    monkeypatch.setattr(upstream.time,'monotonic',lambda:clock[0])
    calls=[]
    def fail(**kwargs):
        calls.append(kwargs)
        raise ProviderError(status)
    fake=SimpleNamespace(models=SimpleNamespace(generate_content=fail,embed_content=fail))
    if kind=='chat':
        adapter=GeminiChatAdapter(client=fake)
        invoke=lambda:adapter.step([])
    elif kind=='embedding':
        adapter=GeminiEmbeddingAdapter(api_key='SECRET_KEY')
        adapter._client=fake
        invoke=lambda:adapter.embed_text('private footage')
    else:
        adapter=GeminiVerificationAdapter(api_key='SECRET_KEY')
        adapter._client=fake
        invoke=lambda: adapter._request(b'image','question') if adapter.available else (_ for _ in ()).throw(adapter.unavailable())
    adapter.available=True
    with pytest.raises(ModelUnavailable) as caught:
        invoke()
    assert caught.value.details=={'provider_status':status,'retry_after_sec':3}
    assert 'SECRET_KEY' not in str(caught.value)
    assert caught.value.__cause__ is None
    assert not adapter.available
    with pytest.raises(ModelUnavailable):
        invoke()
    assert len(calls)==1
    clock[0]+=4
    assert adapter.available
    assert not adapter.unavailable().details


def test_retry_hint_bounded_and_not_parsed_from_secret_text(monkeypatch):
    adapter=GeminiChatAdapter(client=SimpleNamespace())
    adapter.available=True
    assert adapter.provider_failure(ProviderError(429,'999999'),'chat').details['retry_after_sec']==300
    assert adapter.provider_failure(ProviderError(503,'SECRET_KEY'),'chat').details['retry_after_sec']==15
    error=adapter.provider_failure(ProviderError(403),'chat')
    assert error.details=={'provider_status':403}
    assert 'SECRET_KEY' not in str(error)


def test_chat_429_persisted_health_retry_header_and_recovery(tmp_path,footage,monkeypatch):
    clock=[100.0]
    monkeypatch.setattr(upstream.time,'monotonic',lambda:clock[0])
    def fail(**kwargs):raise ProviderError(429)
    fake=SimpleNamespace(models=SimpleNamespace(generate_content=fail),close=lambda:None)
    adapter=GeminiChatAdapter(client=fake)
    adapter.available=True
    app=create_app(Settings(data_dir=tmp_path,worker_enabled=False,relevance_threshold=.5),TestEmbedding(),MissingVerification(),adapter)
    with TestClient(app) as client:
        video=ready(client,footage)
        key=client.post('/api/v1/chats',json={'video_ids':[video['video_id']]}).json()['data']['chat_id']
        client.post('/api/v1/chats/'+key+'/messages',json={'message':'find bag'})
        app.state.service.run_one()
        chat=client.get('/api/v1/chats/'+key).json()['data']
        assert chat['status']=='failed' and chat['error']['code']=='MODEL_UNAVAILABLE'
        assert chat['error']['details']=={'provider_status':429,'retry_after_sec':3}
        assert 'SECRET_KEY' not in str(chat)
        assert not client.get('/api/v1/health').json()['data']['capabilities']['chat']
        response=client.post('/api/v1/chats/'+key+'/messages',json={'message':'retry'})
        assert response.status_code==503 and response.headers['Retry-After']=='3'
        clock[0]+=4
        assert client.get('/api/v1/health').json()['data']['capabilities']['chat']
        fake.models.generate_content=lambda **kwargs:call('finish_response',{'reason':'needs_input','clarification':'query'})
        assert client.post('/api/v1/chats/'+key+'/messages',json={'message':'retry'}).status_code==202
        app.state.service.run_one()
        assert client.get('/api/v1/chats/'+key).json()['data']['status']=='idle'


def test_failed_startup_smoke_requires_reload_and_recovers(monkeypatch):
    clock=[100.0]
    monkeypatch.setattr(upstream.time,'monotonic',lambda:clock[0])
    fake=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs:(_ for _ in ()).throw(ProviderError(429))),close=lambda:None)
    adapter=GeminiChatAdapter(client=fake)
    with pytest.raises(ModelUnavailable):adapter.load()
    assert not adapter.available and not adapter.reload_due
    clock[0]+=4
    assert not adapter.available and adapter.reload_due
    fake.models.generate_content=lambda **kwargs:call('finish_response',{'reason':'needs_input','clarification':'query'})
    adapter.load()
    assert adapter.available and not adapter.reload_due


def test_embedding_503_search_failure_persisted_without_partial_results(tmp_path,footage):
    embedding=TestEmbedding()
    app=create_app(Settings(data_dir=tmp_path,worker_enabled=False,relevance_threshold=.5),embedding,MissingVerification())
    with TestClient(app) as client:
        video=ready(client,footage)
        def unavailable(query):
            raise ModelUnavailable('Google AI is temporarily unavailable. Retry after the cooldown.',{'provider_status':503,'retry_after_sec':15})
        embedding.embed_text=unavailable
        accepted=client.post('/api/v1/searches',json={'query':'a bag','video_ids':[video['video_id']]}).json()['data']
        app.state.service.run_one()
        search=client.get('/api/v1/searches/'+accepted['search_id']).json()['data']
        job=client.get('/api/v1/jobs/'+accepted['job']['job_id']).json()['data']
        assert search['status']=='failed' and search['results']==[]
        assert job['error']==search['error']
        assert search['error']['code']=='MODEL_UNAVAILABLE'
        assert search['error']['details']=={'provider_status':503,'retry_after_sec':15}
