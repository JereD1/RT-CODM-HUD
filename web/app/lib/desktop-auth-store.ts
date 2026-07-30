export interface PendingCode {
    userId: string;
    orgId: string | null;
    expiresAt: number;
  }
  
  // In-memory, short-lived (2 min), one-time-use pairing codes for the
  // desktop app's sign-in flow. Same caveat as other in-memory state in this
  // app (e.g. stateByBroadcastId) — resets on restart/redeploy, not shared
  // across serverless instances. Acceptable here since codes expire in 2
  // minutes and are single-use; move to Redis/DB if this ever needs to
  // survive across instances.
  export const pendingCodes = new Map<string, PendingCode>();
  export const CODE_TTL_MS = 2 * 60 * 1000;
  
  export function cleanupExpiredCodes() {
    const now = Date.now();
    for (const [code, entry] of pendingCodes) {
      if (entry.expiresAt < now) pendingCodes.delete(code);
    }
  }