import { NextResponse } from 'next/server';
import { getDb } from '@/lib/mongo';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const EXPRESS_URL = (process.env.EXPRESS_URL || 'http://127.0.0.1:3090').replace(/\/$/, '');

export async function GET() {
  const checks = { mongo: false, auth: false };

  try {
    const db = await getDb();
    await db.command({ ping: 1 });
    checks.mongo = true;
  } catch {
    checks.mongo = false;
  }

  try {
    const response = await fetch(`${EXPRESS_URL}/health`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(3000),
    });
    checks.auth = response.ok;
  } catch {
    checks.auth = false;
  }

  const healthy = checks.mongo && checks.auth;
  return NextResponse.json(
    { status: healthy ? 'ok' : 'degraded', service: 'app', checks },
    { status: healthy ? 200 : 503 },
  );
}
