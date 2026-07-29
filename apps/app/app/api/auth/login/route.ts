import { NextResponse } from 'next/server';
import { loginBookmaker } from '@/lib/bookmaker';
import { getUsers } from '@/lib/mongo';
import { encrypt } from '@/lib/crypto';
import { createSession } from '@/lib/session';
import { findHouse, DEFAULT_HOUSE, houseMode } from '@/lib/houses';
import { ensureActivationInvoice } from '@/lib/invoices';

export async function POST(req: Request) {
  let body: {
    email?: string;
    password?: string;
    autoReconnect?: boolean;
    house?: string;
  };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Requisição inválida.' }, { status: 400 });
  }

  const email = body.email?.trim().toLowerCase();
  const password = body.password;
  const autoReconnect = Boolean(body.autoReconnect);
  const house = findHouse(body.house)?.id ?? DEFAULT_HOUSE;

  if (!email || !password) {
    return NextResponse.json(
      { error: 'Informe e-mail e senha.' },
      { status: 400 },
    );
  }

  // 1) Valida na casa de apostas escolhida (via Express → plataforma).
  const result = await loginBookmaker(email, password, house);
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
    house,
    lotogreenToken: result.token,
    tokenObtidoEm: now,
    autoReconnect,
    atualizadoEm: now,
    ultimoLogin: now,
  };

  // Casas do modo navegador (Esportiva/Bateu) EXIGEM a senha guardada: o
  // house-agent reloga (headless) a cada início de jogo. Casas http só guardam
  // se o usuário marcou reconexão automática.
  const mustStorePassword = autoReconnect || houseMode(house) === 'browser';
  if (mustStorePassword) {
    update.encryptedPassword = encrypt(password);
  }

  await users.updateOne(
    { email, house },
    {
      $set: update,
      ...(mustStorePassword ? {} : { $unset: { encryptedPassword: '' } }),
      $setOnInsert: { criadoEm: now },
    },
    { upsert: true },
  );

  // Toda conta possui uma única fatura interna de ativação do automático.
  // A criação é idempotente e não chama a PixGo neste momento.
  await ensureActivationInvoice(email);

  // 3) Emite a nossa sessão (cookie httpOnly), guardando a casa escolhida.
  await createSession(email, house);

  return NextResponse.json({ ok: true });
}
