import type { Chat } from '../api/types';

/** One status request at a time; stop on a terminal state, error or disposal. */
export function pollConversation(read: () => Promise<Chat>, update: (chat: Chat) => void, fail: (error: unknown) => void) {
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout>;
  const poll = async () => {
    try {
      const latest = await read();
      if (cancelled) return;
      update(latest);
      if (latest.status === 'running') timer = setTimeout(poll, 2000);
    } catch (error) { if (!cancelled) fail(error); }
  };
  timer = setTimeout(poll, 2000);
  return () => { cancelled = true; clearTimeout(timer); };
}
