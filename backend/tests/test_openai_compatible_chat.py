import json
from types import SimpleNamespace

from google.genai import types

from app.chat import OpenAICompatibleChatAdapter


class Completions:
    def __init__(self): self.requests = []
    def create(self, **kwargs):
        self.requests.append(kwargs)
        call = SimpleNamespace(id='call_1', function=SimpleNamespace(name='finish_response', arguments=json.dumps({'reason':'needs_input','clarification':'query'})))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call],content=None))])


def test_openai_compatible_tool_calls_round_trip_to_backend_history():
    completions = Completions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions),close=lambda:None)
    adapter = OpenAICompatibleChatAdapter(client=client,model='gemma4:31b-cloud')
    adapter.available = True
    initial = types.Content(role='user',parts=[types.Part.from_text(text='context')])
    first = adapter.step([initial])
    assert first.function_calls[0].id == 'call_1'
    response_part = types.Part.from_function_response(name='finish_response',response={'data':{'ok':True}})
    response_part.function_response.id='call_1'
    adapter.step([initial,first.candidates[0].content,types.Content(role='user',parts=[response_part])])
    messages = completions.requests[-1]['messages']
    assert [item['role'] for item in messages] == ['system','user','assistant','tool']
    assert messages[-1]['tool_call_id'] == 'call_1'
    assert json.loads(messages[-1]['content']) == {'data':{'ok':True}}
    assert completions.requests[-1]['model'] == 'gemma4:31b-cloud'


def test_chat_config_uses_ollama_defaults(monkeypatch):
    monkeypatch.delenv('CHAT_BASE_URL',raising=False)
    monkeypatch.delenv('CHAT_MODEL',raising=False)
    monkeypatch.delenv('CHAT_API_KEY',raising=False)
    monkeypatch.delenv('OLLAMA_API_KEY',raising=False)
    client=SimpleNamespace(close=lambda:None)
    adapter=OpenAICompatibleChatAdapter(client=client)
    assert adapter.base_url=='http://localhost:11434/v1'
    assert adapter.model=='gemma4:31b-cloud'
    assert adapter.api_key=='ollama'
