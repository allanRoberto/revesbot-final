import { NextResponse } from 'next/server';
import { loginBookmaker } from '@/lib/bookmaker';
import { getUsers } from '@/lib/mongo';
import { encrypt } from '@/lib/crypto';
import { createSession } from '@/lib/session';

export async function POST(req: Request) {
  let body: { email?: string; password?: string; autoReconnect?: boolean };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Requisição inválida.' }, { status: 400 });
  }

  const email = body.email?.trim().toLowerCase();
  const password = body.password;
  const autoReconnect = Boolean(body.autoReconnect);

  if (!email || !password) {
    return NextResponse.json(
      { error: 'Informe e-mail e senha.' },
      { status: 400 },
    );
  }

  // 1) Valida na casa de apostas (via Express → LotoGreen).
  const result = await loginBookmaker(email, password);
  if (!result.ok || !result.token) {
    return NextResponse.json(
      { error: result.error ?? 'Falha no login.' },
      { status: result.status },
    );
  }

  // 2) Persiste/atualiza o usuário no nosso banco.
  const now = new Date();
  const users = await getUsers();

  const update: Record<string, unknown> = {
    email,
    lotogreenToken: result.token,
    tokenObtidoEm: now,
    autoReconnect,
    atualizadoEm: now,
    ultimoLogin: now,
  };

  if (autoReconnect) {
    // Guarda a senha criptografada (reversível) para reconectar quando expirar.
    update.encryptedPassword = encrypt(password);
  }

  await users.updateOne(
    { email },
    {
      $set: update,
      // Remove a senha salva se o usuário desmarcou a reconexão automática.
      ...(autoReconnect ? {} : { $unset: { encryptedPassword: '' } }),
      $setOnInsert: { criadoEm: now },
    },
    { upsert: true },
  );

  // 3) Emite a nossa sessão (cookie httpOnly).
  await createSession(email);

  return NextResponse.json({ ok: true });
}
