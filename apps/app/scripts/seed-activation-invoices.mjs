import { createHash } from 'node:crypto';
import nextEnv from '@next/env';
import { MongoClient } from 'mongodb';

const { loadEnvConfig } = nextEnv;
loadEnvConfig(process.cwd());

const mongoUrl = process.env.MONGO_URL;
const databaseName = process.env.MONGO_DB || 'roleta_db';
if (!mongoUrl) {
  throw new Error('MONGO_URL não configurada.');
}

function invoiceId(email) {
  const digest = createHash('sha256')
    .update(email)
    .digest('hex')
    .slice(0, 24);
  return `activation_${digest}`;
}

const client = new MongoClient(mongoUrl);
await client.connect();

try {
  const database = client.db(databaseName);
  const users = database.collection('app_users');
  const invoices = database.collection('automation_invoices');
  const emails = (await users.distinct('email'))
    .map((email) => String(email || '').trim().toLowerCase())
    .filter(Boolean);

  let created = 0;
  let existing = 0;
  for (const email of emails) {
    const now = new Date();
    const result = await invoices.updateOne(
      { invoiceId: invoiceId(email) },
      {
        $setOnInsert: {
          invoiceId: invoiceId(email),
          email,
          type: 'activation',
          description: 'Ativação do bot automático',
          amountCents: 3000,
          status: 'pending',
          criadoEm: now,
          atualizadoEm: now,
        },
      },
      { upsert: true },
    );
    if (result.upsertedCount > 0) created += 1;
    else existing += 1;
  }

  console.log(
    JSON.stringify({
      users: emails.length,
      activationInvoicesCreated: created,
      alreadyExisted: existing,
    }),
  );
} finally {
  await client.close();
}
