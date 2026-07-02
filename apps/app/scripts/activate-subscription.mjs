#!/usr/bin/env node
/**
 * Libera (ativa) uma assinatura manualmente.
 *
 *   node scripts/activate-subscription.mjs <email> [planId] [dias]
 *
 * Ex.:  node scripts/activate-subscription.mjs cliente@x.com mensal
 *       node scripts/activate-subscription.mjs cliente@x.com trimestral
 *       node scripts/activate-subscription.mjs cliente@x.com mensal 45
 *
 * Renova a partir do vencimento atual se a assinatura ainda estiver ativa.
 * Lê MONGO_URL/MONGO_DB do .env.local (mesmo do app).
 */
import { MongoClient } from 'mongodb';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));

function loadEnv() {
  try {
    const txt = readFileSync(join(__dirname, '..', '.env.local'), 'utf8');
    for (const line of txt.split('\n')) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
    }
  } catch {
    /* usa env do processo */
  }
}

const PLAN_DAYS = { mensal: 30, trimestral: 90, vitalicio: 36500 };

async function main() {
  loadEnv();
  const [email, planId = 'mensal', daysArg] = process.argv.slice(2);
  if (!email) {
    console.error('Uso: node scripts/activate-subscription.mjs <email> [planId] [dias]');
    process.exit(1);
  }
  const days = Number(daysArg) || PLAN_DAYS[planId] || 30;

  const uri = process.env.MONGO_URL;
  if (!uri) {
    console.error('MONGO_URL não definida (.env.local).');
    process.exit(1);
  }
  const client = new MongoClient(uri);
  await client.connect();
  const db = client.db(process.env.MONGO_DB || 'roleta_db');
  const subs = db.collection('app_subscriptions');

  const now = new Date();
  const existing = await subs.findOne({ email });
  const base =
    existing?.status === 'active' &&
    existing?.expiresAt &&
    new Date(existing.expiresAt) > now
      ? new Date(existing.expiresAt)
      : now;
  const expiresAt = new Date(base.getTime() + days * 24 * 60 * 60 * 1000);

  await subs.updateOne(
    { email },
    {
      $set: {
        email,
        status: 'active',
        planId,
        activatedAt: now,
        expiresAt,
        atualizadoEm: now,
      },
      $setOnInsert: { criadoEm: now },
    },
    { upsert: true },
  );

  console.log(`✅ Assinatura ativada: ${email} | plano ${planId} | +${days} dias`);
  console.log(`   Expira em: ${expiresAt.toISOString()}`);
  await client.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
