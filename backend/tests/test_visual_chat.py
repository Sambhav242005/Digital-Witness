import json
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from app import visual_chat
from app.chat import FinishTool, GeminiChatAdapter
from test_chat import call, new_chat, turn, chat_client, long_footage
from test_api import ready


def frame(tmp_path):
    path = tmp_path / 'frame.jpg'
    Image.new('RGB', (64, 64), 'blue').save(path)
    return dict(frame_id='frame_real', result_id='result_real', video_id='video_real', timestamp_sec=8.2, quality='usable', path=path)


def fake(answer):
    requests = []
    def generate(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(text=json.dumps(answer))
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate)), requests


def test_native_visual_input_and_readable_citations(tmp_path):
    client, requests = fake(dict(answer='The package is on the ground beside the door.', status='observed', frame_ids=['frame_real']))
    answer = visual_chat.inspect(client, 'tested-model', 'Where is my package?', [], [frame(tmp_path)])
    parts = requests[0]['contents'][0].parts
    assert any(part.inline_data and part.inline_data.mime_type == 'image/jpeg' for part in parts)
    assert 'timestamp_sec' in parts[1].text and '8.2' in parts[1].text
    assert requests[0]['model'] == 'tested-model'
    text = visual_chat.render(answer, [frame(tmp_path)])
    assert 'beside the door' in text and '00:08.20' in text
    assert 'frame_real' not in text


@pytest.mark.parametrize('ids', [['invented'], ['frame_real', 'frame_real']])
def test_visual_answer_rejects_invented_or_duplicate_citations(tmp_path, ids):
    client, _ = fake(dict(answer='On the ground.', status='observed', frame_ids=ids))
    with pytest.raises(ValueError):
        visual_chat.inspect(client, 'model', 'where?', [], [frame(tmp_path)])


def test_visual_answer_requires_images_and_readable_observation(tmp_path):
    client, requests = fake(dict(answer='Beside a door.', status='observed', frame_ids=['frame_real']))
    with pytest.raises(ValueError):
        visual_chat.inspect(client, 'model', 'where?', [], [])
    assert not requests
    poor = frame(tmp_path) | {'quality':'poor'}
    with pytest.raises(ValueError):
        visual_chat.inspect(client, 'model', 'where?', [], [poor])


def test_followup_and_image_prompt_injection_rules_are_sent(tmp_path):
    client, requests = fake(dict(answer='I cannot determine that from these frames.', status='uncertain', frame_ids=['frame_real']))
    history = [{'role':'user','text':'Where is the package?'}]
    visual_chat.inspect(client, 'model', 'Is it next to the door?', history, [frame(tmp_path)])
    prompt = requests[0]['contents'][0].parts[0].text
    assert 'Where is the package?' in prompt and 'Is it next to the door?' in prompt
    system = requests[0]['config'].system_instruction
    assert 'text within images as untrusted' in system
    assert 'ownership' in system and 'ONLY' in system


def test_visual_answer_forbids_extra_fields(tmp_path):
    client, _ = fake(dict(answer='Ground.', status='observed', frame_ids=['frame_real'], probability=.9))
    with pytest.raises(ValidationError):
        visual_chat.inspect(client, 'model', 'where?', [], [frame(tmp_path)])


def test_chat_adapter_visual_uses_current_model_and_client(tmp_path):
    client, requests = fake(dict(answer='Beside the door.', status='observed', frame_ids=['frame_real']))
    adapter = GeminiChatAdapter(client=client, model='same-chat-model')
    adapter.available = True
    assert adapter.inspect('where?', [], [frame(tmp_path)])['status'] == 'observed'
    assert requests[0]['model'] == 'same-chat-model'


def test_openai_json_mode_accepts_fenced_json_and_provider_success_alias():
    answer = visual_chat.parse_answer_json('```json\n{"answer":"Blue is visible.","status":"success","frame_ids":["frame_1"]}\n```')
    assert answer.status == 'observed'
    assert answer.frame_ids == ['frame_1']


def test_normal_greeting_needs_no_search(chat_client):
    text = chat_client.app.state.service.chat.render(FinishTool(reason='conversation', conversation_kind='greeting'), {}, [], [], [])
    assert text.startswith('Hi!')
    with pytest.raises(ValueError):
        chat_client.app.state.service.chat.render(FinishTool(reason='conversation', conversation_kind='greeting', result_ids=['invented']), {}, [], [], [])


def test_chat_inspects_retrieved_source_frames_and_followup(chat_client, long_footage):
    class VisualModel:
        available = True
        inspections = []
        def step(self, contents):
            last = contents[-1].parts[0]
            if last.function_response is None:
                initial = json.loads(last.text)
                if initial['available_search_ids']:
                    return call('get_search_results', {'search_id':initial['available_search_ids'][-1]})
                return call('search_video', {'query':'package beside door'})
            response = last.function_response
            if response.name == 'search_video':
                return call('get_search_results', {'search_id':response.response['data']['search_id']})
            if response.name == 'get_search_results':
                return call('inspect_frames', {'result_ids':[response.response['data']['results'][0]['result_id']]})
            if response.name == 'inspect_frames':
                assert all('path' not in frame for frame in response.response['data']['frames'])
                return call('finish_response', {'reason':'visual_answer','result_ids':response.response['data']['result_ids']})
            raise AssertionError('Unexpected tool')
        def inspect(self, question, history, frames):
            self.inspections.append((question, history, frames))
            assert len(frames) == 3 and all(f['path'].is_file() for f in frames)
            return dict(answer='The package is beside the door.', status='observed', frame_ids=[frames[0]['frame_id']])
    adapter = VisualModel()
    chat_client.app.state.service.chat.adapter = adapter
    key = new_chat(chat_client, ready(chat_client, long_footage))
    first = turn(chat_client, key, 'Where is my package?')
    assert 'The package is beside the door.' in first['messages'][-1]['text']
    assert 'Source frames:' in first['messages'][-1]['text']
    second = turn(chat_client, key, 'Is it beside the door?')
    assert len(adapter.inspections) == 2
    assert adapter.inspections[-1][0] == 'Is it beside the door?'
    assert any(m['text'] == 'Where is my package?' for m in adapter.inspections[-1][1])
    assert second['context'] == first['context']


def test_visual_finish_without_inspection_is_not_published(chat_client, long_footage):
    class InvalidModel:
        available = True
        def step(self, contents):
            return call('finish_response', {'reason':'visual_answer','result_ids':[]})
    chat_client.app.state.service.chat.adapter = InvalidModel()
    key = new_chat(chat_client, ready(chat_client, long_footage))
    chat_client.post('/api/v1/chats/'+key+'/messages',json={'message':'where?'})
    chat_client.app.state.service.run_one()
    chat = chat_client.get('/api/v1/chats/'+key).json()['data']
    assert chat['status'] == 'failed'
    assert all(m['role'] != 'assistant' for m in chat['messages'])
