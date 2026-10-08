import { afterEach, describe, expect, it, vi } from 'vitest';
import { pollConversation } from './chat-poll';
import type { Chat } from '../api/types';
const running: Chat = { chat_id: 'chat_1', video_ids: ['vid_1'], created_at: '', updated_at: '', status: 'running', active_turn_id: 'turn_1', context: null, messages: [], error: null };
afterEach(() => vi.useRealTimers());

describe('conversation polling lifecycle', () => {
  it('polls every two seconds and stops on idle or failed', async () => {
    for (const status of ['idle', 'failed'] as const) {
      vi.useFakeTimers();
      const read = vi.fn().mockResolvedValueOnce(running).mockResolvedValueOnce({ ...running, status });
      const update = vi.fn(); const fail = vi.fn();
      const stop = pollConversation(read, update, fail);
      await vi.advanceTimersByTimeAsync(1999); expect(read).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1); expect(read).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(2000); expect(update).toHaveBeenLastCalledWith(expect.objectContaining({ status }));
      await vi.advanceTimersByTimeAsync(10000); expect(read).toHaveBeenCalledTimes(2); expect(fail).not.toHaveBeenCalled();
      stop(); vi.useRealTimers();
    }
  });
  it('disposal prevents pending requests and ignores stale in-flight responses', async () => {
    vi.useFakeTimers();
    let resolve!: (chat: Chat) => void;
    const read = vi.fn(() => new Promise<Chat>((done) => { resolve = done; }));
    const update = vi.fn(); const fail = vi.fn();
    const stop = pollConversation(read, update, fail);
    await vi.advanceTimersByTimeAsync(2000); stop(); resolve(running);
    await vi.advanceTimersByTimeAsync(10000);
    expect(read).toHaveBeenCalledTimes(1); expect(update).not.toHaveBeenCalled(); expect(fail).not.toHaveBeenCalled();
  });
  it('does not overlap slow status requests', async () => {
    vi.useFakeTimers();
    const read = vi.fn(() => new Promise<Chat>(() => {}));
    const stop = pollConversation(read, vi.fn(), vi.fn());
    await vi.advanceTimersByTimeAsync(20000); expect(read).toHaveBeenCalledTimes(1); stop();
  });
  it('stops after a connection error so reconnect can recover persisted state', async () => {
    vi.useFakeTimers(); const problem = new Error('offline');
    const read = vi.fn().mockRejectedValue(problem); const fail = vi.fn();
    const stop = pollConversation(read, vi.fn(), fail);
    await vi.advanceTimersByTimeAsync(10000); expect(read).toHaveBeenCalledTimes(1); expect(fail).toHaveBeenCalledWith(problem); stop();
  });
});
