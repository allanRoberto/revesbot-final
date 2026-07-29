import crypto from 'crypto';

function internalToken(): string {
  return process.env.AUTOMATION_INTERNAL_TOKEN || process.env.BET_WS_TOKEN || '';
}
export function isValidInternalRequest(req: Request): boolean {
  const expected = internalToken();
  const received = req.headers.get('x-automation-token') || '';
  if (!expected || !received) return false;
  const a = Buffer.from(expected);
  const b = Buffer.from(received);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
