import { useCallback, useEffect, useRef, useState } from 'react';
import { discardPreparedRun, prepareRunTransfer, RunUploadHttpError } from './createRun';

type TransferPacket = Parameters<typeof prepareRunTransfer>[0];

type TransferState =
  | { phase: 'uploading'; percent?: number }
  | { phase: 'ready'; uploadId: string }
  | { phase: 'failed'; error: unknown };

interface TransferAttempt {
  packet: TransferPacket;
  send: ReturnType<typeof prepareRunTransfer>;
  controller?: AbortController;
  uploadId?: string;
  startRequested: boolean;
}

function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();

  // Random bytes are available even when randomUUID requires a secure context.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
}

function release(uploadId: string) {
  void discardPreparedRun(uploadId, AbortSignal.timeout(5_000)).catch(() => {
    // The server expires abandoned uploads when the client cannot release one.
  });
}

export function usePreparedRun(packet: TransferPacket | null) {
  const current = useRef<TransferAttempt | null>(null);
  const [snapshot, setSnapshot] = useState<{ packet: TransferPacket; state: TransferState }>();

  const transfer = useCallback(async (attempt: TransferAttempt) => {
    if (attempt.controller || attempt.uploadId) return;
    const controller = new AbortController();
    attempt.controller = controller;
    const publish = (state: TransferState) => {
      if (!controller.signal.aborted) setSnapshot({ packet: attempt.packet, state });
    };

    publish({ phase: 'uploading' });
    try {
      const { upload_id: uploadId } = await attempt.send(controller.signal, (percent) => {
        publish({ phase: 'uploading', percent });
      });
      if (controller.signal.aborted) {
        release(uploadId);
        return;
      }
      attempt.uploadId = uploadId;
      publish({ phase: 'ready', uploadId });
    } catch (error) {
      if (error instanceof RunUploadHttpError && (error.status === 404 || error.status === 410)) {
        attempt.send = prepareRunTransfer(attempt.packet, newIdempotencyKey());
      }
      publish({ phase: 'failed', error });
    } finally {
      attempt.controller = undefined;
    }
  }, []);

  useEffect(() => {
    if (!packet) return;
    const attempt: TransferAttempt = {
      packet,
      send: prepareRunTransfer(packet, newIdempotencyKey()),
      startRequested: false,
    };
    current.current = attempt;
    queueMicrotask(() => {
      if (current.current === attempt) void transfer(attempt);
    });
    return () => {
      attempt.controller?.abort();
      if (attempt.uploadId && !attempt.startRequested) release(attempt.uploadId);
      current.current = null;
    };
  }, [packet, transfer]);

  const state = snapshot?.packet === packet ? snapshot.state : undefined;

  function start(): string | undefined {
    const attempt = current.current;
    if (!attempt || attempt.packet !== packet || !attempt.uploadId) return;
    attempt.startRequested = true;
    return attempt.uploadId;
  }

  function retry() {
    const attempt = current.current;
    if (attempt?.packet === packet) void transfer(attempt);
  }

  function replaceExpired(uploadId: string) {
    const attempt = current.current;
    if (!attempt || attempt.packet !== packet || attempt.uploadId !== uploadId) return;
    release(uploadId);
    attempt.uploadId = undefined;
    attempt.startRequested = false;
    attempt.send = prepareRunTransfer(attempt.packet, newIdempotencyKey());
    void transfer(attempt);
  }

  return { state, start, retry, replaceExpired };
}
