import { afterEach, describe, expect, it, vi } from 'vitest';
import { liveApi } from './client';
import { mockApi } from './mock';
import type { Chat } from './types';

const chat: Chat = { chat_id: 'chat_123', video_ids: ['vid_1'], created_at: '2026-10-08T00:00:00Z', updated_at: '2026-10-08T00:00:00Z', status: 'idle', active_turn_id: null, context: null, messages: [], error: null };
afterEach(() => vi.unstubAllGlobals());

describe('chat API integration contract', () => {
  it('creates a backend conversation scoped to selected recording IDs', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: chat }), { status: 201 }));
    vi.stubGlobal('fetch', fetch);
    expect(await liveApi.createChat(['vid_1'])).toEqual(chat);
    expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/v1/chats', expect.objectContaining({ method: 'POST', body: '{"video_ids":["vid_1"]}', cache: 'no-store' }));
  });
  it('encodes opaque chat IDs and posts only the follow-up message', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { chat_id: 'opaque/id', turn_id: 'turn_1' } }), { status: 202 }));
    vi.stubGlobal('fetch', fetch);
    await liveApi.sendChatMessage('opaque/id', 'Only show matches after 2 minutes.');
    expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/v1/chats/opaque%2Fid/messages', expect.objectContaining({ method: 'POST', body: '{"message":"Only show matches after 2 minutes."}' }));
  });
  it('recovers running chats including stored context and referenced evidence', async () => {
    const running = { ...chat, status: 'running', active_turn_id: 'turn_1', context: { query: 'bag', video_ids: ['vid_1'], time_range: null, event_types: [] } };
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: running })));
    vi.stubGlobal('fetch', fetch);
    expect(await liveApi.getChat('chat_123')).toEqual(running);
    expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/v1/chats/chat_123', expect.objectContaining({ cache: 'no-store' }));
  });
  it('preserves quota errors, retry timing and request ID for recovery UI', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'CHAT_UNAVAILABLE', message: 'Provider quota exhausted.', details: {} }, request_id: 'req_1' }), { status: 429, headers: { 'Retry-After': '30' } })));
    await expect(liveApi.sendChatMessage('chat_123', 'Find a bag')).rejects.toMatchObject({ status: 429, retryAfterSec: 30, requestId: 'req_1', code: 'CHAT_UNAVAILABLE' });
  });
  it('labels mocked reasoning and exposes only retrievable sample evidence IDs', async () => {
    const created = await mockApi.createChat(['vid_demo_entrance']);
    await mockApi.sendChatMessage(created.chat_id, 'Find someone carrying a bag');
    const completed = await mockApi.getChat(created.chat_id);
    expect(completed.status).toBe('idle');
    const assistant = completed.messages.at(-1)!;
    expect(assistant.text).toContain('MOCK response');
    const search = await mockApi.getSearch(assistant.search_ids[0]);
    expect(search.status).toBe('succeeded');
    expect(assistant.result_ids).toEqual(search.results.map((result) => result.result_id));
    expect((await mockApi.health()).capabilities.chat).toBe(true);
  });
});
