'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api } from '@/api/client';
import { ApiError } from '@/api/errors';
import type { Chat, Search, SearchResult, Video } from '@/api/types';
import { pollConversation } from './chat-poll';

const mode = process.env.NEXT_PUBLIC_USE_MOCKS === 'true' ? 'mock' : 'live';
const storageKey = (ids: string[]) => `dw_chat_${mode}_${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1'}_${[...ids].sort().join(',')}`;
function savedChat(key: string) { try { return window.sessionStorage.getItem(key); } catch { return null; } }
function saveChat(key: string, id: string | null) { try { if (id) window.sessionStorage.setItem(key, id); else window.sessionStorage.removeItem(key); } catch { /* Chat remains usable without browser storage. */ } }
function errorText(error: unknown) {
  if (error instanceof ApiError) return `${error.message}${error.retryAfterSec !== null ? ` Try again in ${error.retryAfterSec} seconds.` : ''}${error.requestId ? ` Request ID: ${error.requestId}` : ''}`;
  return error instanceof Error ? error.message : 'Could not complete the conversation request.';
}
function time(seconds: number) { return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`; }

export function ChatPanel({ videos, available, onReview }: { videos: Video[]; available: boolean; onReview: (search: Search, result: SearchResult | null) => void }) {
  const ids = videos.map((video) => video.video_id);
  const scope = storageKey(ids);
  const [chat, setChat] = useState<Chat | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [searches, setSearches] = useState<Record<string, Search>>({});
  const [retry, setRetry] = useState(0);
  const generation = useRef(0);
  const currentChat = useRef<Chat | null>(null);
  currentChat.current = chat;
  useEffect(() => () => { generation.current++; }, []);

  // Scope changes invalidate old responses; saved conversations are recovered after refresh.
  useEffect(() => {
    const version = ++generation.current;
    let cancelled = false;
    setChat(null); setSearches({}); setError(''); setSending(false); setLoading(true);
    const id = savedChat(scope);
    if (!id) { setLoading(false); return () => { cancelled = true; }; }
    void api.getChat(id).then((recovered) => {
      if (!cancelled && version === generation.current) setChat(recovered);
    }).catch((problem) => {
      if (cancelled || version !== generation.current) return;
      if (problem instanceof ApiError && problem.status === 404) saveChat(scope, null);
      setError(errorText(problem));
    }).finally(() => { if (!cancelled && version === generation.current) setLoading(false); });
    return () => { cancelled = true; };
  }, [scope, retry]);

  // Recursive timeouts prevent overlapping requests and stop after idle/failed or unmount.
  useEffect(() => {
    if (!chat || chat.status !== 'running') return;
    const version = generation.current;
    return pollConversation(() => api.getChat(chat.chat_id), (latest) => {
      if (version !== generation.current) return;
      setChat(latest); setError('');
    }, (problem) => { if (version === generation.current) setError(errorText(problem)); });
  }, [chat]);

  useEffect(() => {
    if (!chat || chat.status === 'running') return;
    let cancelled = false;
    const version = generation.current;
    const searchIds = [...new Set(chat.messages.flatMap((entry) => entry.search_ids))];
    void Promise.all(searchIds.map(async (id) => [id, await api.getSearch(id)] as const)).then((entries) => {
      if (!cancelled && version === generation.current) setSearches(Object.fromEntries(entries));
    }).catch((problem) => { if (!cancelled && version === generation.current) setError(errorText(problem)); });
    return () => { cancelled = true; };
  }, [chat]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = message.trim();
    if (!text || text.length > 2000 || sending || chat?.status === 'running' || !available || !ids.length || ids.length > 20) return;
    const version = generation.current;
    setSending(true); setError('');
    try {
      const conversation = currentChat.current ?? await api.createChat(ids);
      if (version !== generation.current) return;
      saveChat(scope, conversation.chat_id); setChat(conversation);
      await api.sendChatMessage(conversation.chat_id, text);
      if (version !== generation.current) return;
      // Keep the accepted turn visible even if its first status request fails.
      setMessage(''); setChat({ ...conversation, status: 'running', error: null });
      const latest = await api.getChat(conversation.chat_id);
      if (version === generation.current) setChat(latest);
    } catch (problem) { if (version === generation.current) setError(errorText(problem)); }
    finally { if (version === generation.current) setSending(false); }
  };
  const newConversation = () => { generation.current++; saveChat(scope, null); setChat(null); setSearches({}); setMessage(''); setError(''); };
  const busy = sending || chat?.status === 'running';

  return <section className="panel" aria-labelledby="chat-heading" style={{ padding: '24px' }}>
    <div className="section-heading"><div><span className="eyebrow">ASK ABOUT THE FOOTAGE</span><h2 id="chat-heading">Evidence conversation</h2><p>Ask a question, then refine the same search with follow-ups.</p></div><button className="button button-quiet" type="button" disabled={busy || loading || !chat} onClick={newConversation}>New conversation</button></div>
    <p className="helper-text">{videos.length ? `Selected recordings: ${videos.map((video) => video.camera_label).join(', ')}` : 'Select ready recordings in the search panel to start a conversation.'}</p>
    {!available && <p className="capability-note">Chat is unavailable from the backend right now.</p>}
    {loading && <p role="status">Recovering conversation…</p>}
    <div role="log" aria-label="Evidence conversation messages" aria-live="polite" aria-relevant="additions text">
      {chat?.messages.map((entry) => <article key={entry.message_id} style={{ margin: '16px 0', padding: '16px', border: '1px solid var(--border, #ddd)', borderRadius: '8px' }}>
        <strong>{entry.role === 'user' ? 'You' : 'Assistant'}</strong><p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{entry.text}</p>
        {entry.search_ids.map((id) => {
          const search = searches[id];
          if (!search) return null;
          const referenced = search.results.filter((result) => entry.result_ids.includes(result.result_id));
          return <div key={id}>
            <button className="text-button" type="button" onClick={() => onReview(search, referenced[0] ?? search.results[0] ?? null)}>Review retrieved search ({search.results.length} candidates)</button>
            {referenced.map((result) => <div key={result.result_id}><button type="button" className="text-button" onClick={() => onReview(search, result)}>{result.camera_label} · {time(result.start_sec)}–{time(result.end_sec)} · inspect evidence</button></div>)}
          </div>;
        })}
      </article>)}
    </div>
    {chat?.context && <p className="helper-text">Current search: {chat.context.query}{chat.context.time_range ? ` · ${time(chat.context.time_range.start_sec)}–${time(chat.context.time_range.end_sec)}` : ''}</p>}
    {busy && <p role="status">Searching and reviewing evidence…</p>}
    {chat?.status === 'failed' && <p className="field-error" role="alert">{chat.error?.message ?? 'The turn failed.'} You can send the question again.</p>}
    {error && <div role="alert"><p className="field-error">{error}</p><button className="text-button" type="button" disabled={sending} onClick={() => setRetry((value) => value + 1)}>Reconnect conversation</button></div>}
    <form onSubmit={submit}>
      <label className="field-label" htmlFor="chat-message">Question or follow-up</label>
      <textarea id="chat-message" className="text-input query-input" value={message} onChange={(event) => setMessage(event.target.value)} maxLength={2000} placeholder="Where is the package? Then: is it beside the door? You can also ask for a time range or describe another moment." disabled={busy || loading || !available} />
      <div className="search-submit-row"><span className="helper-text">Footage answers inspect timestamped frames. Describe visible details; ask follow-ups in the same conversation.</span><button type="submit" className="button button-primary" disabled={busy || loading || !available || !ids.length || ids.length > 20 || !message.trim()}>{busy ? 'Working…' : 'Send question'}</button></div>
    </form>
  </section>;
}
