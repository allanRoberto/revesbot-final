import { SignJWT, jwtVerify } from 'jose';
import { cookies } from 'next/headers';
import { DEFAULT_HOUSE } from './houses';

// Sessão PRÓPRIA do nosso app, desacoplada do token da LotoGreen.
// O cookie guarda só o e-mail do usuário; o token da casa fica no Mongo.

const SESSION_COOKIE = 'reves_session';
const MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30 dias

function getSecret(): Uint8Array {
  const secret = process.env.JWT_SECRET;
  if (!secret) throw new Error('JWT_SECRET não definida no ambiente.');
  return new TextEncoder().encode(secret);
}

export interface SessionPayload {
  email: string;
  house: string;
}

export async function createSession(email: string, house: string): Promise<void> {
  const token = await new SignJWT({ email, house })
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuedAt()
    .setExpirationTime(`${MAX_AGE_SECONDS}s`)
    .sign(getSecret());

  const jar = await cookies();
  jar.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
    maxAge: MAX_AGE_SECONDS,
  });
}

export async function getSession(): Promise<SessionPayload | null> {
  const jar = await cookies();
  const token = jar.get(SESSION_COOKIE)?.value;
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, getSecret());
    // house ausente = sessão antiga (pré-multicasa) → assume a casa padrão.
    return {
      email: payload.email as string,
      house: (payload.house as string) || DEFAULT_HOUSE,
    };
  } catch {
    return null;
  }
}

export async function destroySession(): Promise<void> {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
}
