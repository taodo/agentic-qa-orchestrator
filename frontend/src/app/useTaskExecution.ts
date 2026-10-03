import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, publicError } from '../api/client';
import { EXECUTION_HISTORY_LIMIT, getExecution, getExecutions, isActiveJob, requestExecution } from '../api/executions';
import type { CollectionPage, ExecutionJobView } from '../api/types';

export const EXECUTION_POLL_MS = 1500;
interface State {
  taskId: string; job?: ExecutionJobView; history?: CollectionPage<ExecutionJobView>;
  checking: boolean; creating: boolean; refreshing: boolean; verified: boolean; warning?: ApiError;
}
interface Session {
  taskId: string; alive: boolean; reading: boolean; command: boolean; refreshing: boolean; verified: boolean;
  job?: ExecutionJobView; history?: CollectionPage<ExecutionJobView>; missingId?: string;
  timer?: ReturnType<typeof setTimeout>; controller?: AbortController; completed: Set<string>;
}
function safeWarning(failure: unknown) {
  const code = publicError(failure).code;
  const messages: Record<string, string> = {
    TASK_EXECUTION_ALREADY_ACTIVE: 'An execution already exists. Recover it from execution history.',
    TASK_EXECUTION_TERMINAL: 'This Task is terminal. Refresh Task state and use the terminal check.',
    EXECUTION_JOB_NOT_FOUND: 'Execution request not found. Polling stopped; refresh history and inspect Task evidence.',
    RUNTIME_STOPPED: 'Execution is unavailable or stopped safely. Inspect persisted Task state and evidence.',
    NETWORK_ERROR: 'Execution status is uncertain because the API is unreachable. Keep this request; refresh history to recover it.',
  };
  return new ApiError(code, messages[code] ?? 'Execution status could not be verified. Refresh history and inspect Task evidence.');
}

// Each route owns its session. Reads are serialized; POST is never retried.
export function useTaskExecution(taskId: string, onTerminal: () => Promise<void>) {
  const current = useRef<Session | undefined>(undefined);
  const route = useRef(taskId);
  route.current = taskId;
  const terminalCallback = useRef(onTerminal);
  terminalCallback.current = onTerminal;
  const [state, setState] = useState<State>({ taskId, checking: true, creating: false, refreshing: false, verified: false });
  function valid(session: Session) { return session.alive && current.current === session && route.current === session.taskId; }
  function update(session: Session, changes: Partial<State>) {
    if (valid(session)) setState(previous => ({ ...previous, ...changes, taskId: session.taskId }));
  }
  function clearTimer(session: Session) { clearTimeout(session.timer); session.timer = undefined; }
  function schedule(session: Session) {
    clearTimer(session);
    if (valid(session) && isActiveJob(session.job) && !session.missingId && !session.reading && !session.command && !session.refreshing) {
      session.timer = setTimeout(() => { void read(session, 'job'); }, EXECUTION_POLL_MS);
    }
  }
  function retainJob(session: Session, job: ExecutionJobView) {
    session.job = job;
    const old = session.history?.items ?? [];
    const exists = old.some(item => item.id === job.id);
    const items = exists ? old.map(item => item.id === job.id ? job : item) : [job, ...old].slice(0, EXECUTION_HISTORY_LIMIT);
    session.history = { items, total_returned: items.length, truncated: !!session.history?.truncated || (!exists && old.length >= EXECUTION_HISTORY_LIMIT) };
    update(session, { job, history: session.history });
  }
  async function terminal(session: Session, job: ExecutionJobView) {
    if (!valid(session) || session.completed.has(job.id)) return;
    session.completed.add(job.id);
    session.refreshing = true;
    clearTimer(session); update(session, { refreshing: true });
    try {
      await terminalCallback.current(); // Task + Timeline + only mounted evidence.
    } catch (failure) {
      update(session, { warning: safeWarning(failure) });
    } finally {
      if (valid(session)) await read(session, 'history');
      session.refreshing = false; update(session, { refreshing: false }); schedule(session);
    }
  }
  async function read(session: Session, kind: 'history' | 'job') {
    // Internal history recovery may follow a settled POST while its command
    // guard remains held. Public refresh/create cannot overlap that operation.
    if (!valid(session) || session.reading || (session.command && kind === 'job')) return;
    const previous = session.job;
    if (kind === 'job' && (!isActiveJob(previous) || session.missingId)) return;
    clearTimer(session);
    session.reading = true;
    const controller = new AbortController(); session.controller = controller;
    if (kind === 'history') update(session, { checking: true });
    let finished: ExecutionJobView | undefined, missing = false;
    try {
      if (kind === 'history') {
        const history = await getExecutions(session.taskId, controller.signal);
        if (!valid(session)) return;
        const next = history.items.find(isActiveJob) ?? history.items[0];
        session.history = history; session.job = next; session.verified = true;
        if (session.missingId && next?.id !== session.missingId) session.missingId = undefined;
        update(session, { history, job: next, verified: true });
        if (previous && isActiveJob(previous) && next && !isActiveJob(next)) finished = next;
      } else {
        const next = await getExecution(session.taskId, previous!.id, controller.signal);
        if (!valid(session) || session.job?.id !== previous!.id) return;
        retainJob(session, next); update(session, { warning: undefined });
        if (!isActiveJob(next)) finished = next;
      }
    } catch (failure) {
      if (!valid(session)) return;
      const warning = safeWarning(failure);
      update(session, { warning });
      if (kind === 'history') { session.verified = false; update(session, { verified: false }); }
      if (kind === 'job' && warning.code === 'EXECUTION_JOB_NOT_FOUND') {
        session.missingId = previous!.id; missing = true;
      }
    } finally {
      session.reading = false;
      if (session.controller === controller) session.controller = undefined;
      if (kind === 'history') update(session, { checking: false });
    }
    if (!valid(session)) return;
    if (finished) await terminal(session, finished);
    if (missing) await read(session, 'history');
    schedule(session); // Next tick starts only after the previous request settles.
  }
  useEffect(() => {
    const session: Session = { taskId, alive: true, reading: false, command: false, refreshing: false, verified: false, completed: new Set() };
    current.current = session;
    setState({ taskId, checking: true, creating: false, refreshing: false, verified: false });
    void read(session, 'history');
    return () => { session.alive = false; clearTimer(session); session.controller?.abort(); };
    // The session owns callbacks; render changes must not restart its polling.
  }, [taskId]);

  const refresh = useCallback(async () => {
    const session = current.current;
    if (!session || session.taskId !== taskId || session.reading || session.command || session.refreshing) return;
    session.missingId = undefined;
    update(session, { warning: undefined });
    await read(session, 'history');
  }, [taskId]);
  const create = useCallback(async () => {
    const session = current.current;
    if (!session || session.taskId !== taskId || !valid(session) || !session.verified || session.reading ||
        session.command || session.refreshing || isActiveJob(session.job)) return;
    clearTimer(session); session.command = true; update(session, { creating: true, warning: undefined });
    const controller = new AbortController(); session.controller = controller;
    try {
      const job = await requestExecution(taskId, controller.signal);
      if (!valid(session)) return;
      retainJob(session, job);
      if (!isActiveJob(job)) await terminal(session, job);
    } catch (failure) {
      if (!valid(session)) return;
      const warning = safeWarning(failure); update(session, { warning });
      await read(session, 'history'); // Recover backend truth, never retry POST.
      if (!valid(session)) return;
      if (warning.code === 'TASK_EXECUTION_ALREADY_ACTIVE' && isActiveJob(session.job)) update(session, { warning: undefined });
      if (warning.code === 'TASK_EXECUTION_TERMINAL' || warning.code === 'RUNTIME_STOPPED') await terminalCallback.current();
    } finally {
      session.command = false;
      if (session.controller === controller) session.controller = undefined;
      update(session, { creating: false }); schedule(session);
    }
  }, [taskId]);
  const visible = state.taskId === taskId ? state : { taskId, checking: true, creating: false, refreshing: false, verified: false };
  return { ...visible, active: isActiveJob(visible.job), create, refresh };
}
