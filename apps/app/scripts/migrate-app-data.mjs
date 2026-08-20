import { MongoClient } from 'mongodb';

const COLLECTIONS = [
  'app_users',
  'app_subscriptions',
  'automation_runs',
  'automation_bets',
  'automation_billing_accounts',
  'commission_payment_orders',
  'automation_invoices',
  'payment_webhook_events',
];

const sourceUri = process.env.SOURCE_MONGO_URL;
const targetUri = process.env.TARGET_MONGO_URL;
const sourceDbName = process.env.SOURCE_MONGO_DB || 'roleta_db';
const targetDbName = process.env.TARGET_MONGO_DB || 'roleta_db';
const replace = process.argv.includes('--replace');

if (!sourceUri || !targetUri) {
  throw new Error('Defina SOURCE_MONGO_URL e TARGET_MONGO_URL.');
}
if (sourceUri === targetUri && sourceDbName === targetDbName) {
  throw new Error('Origem e destino nao podem ser o mesmo banco.');
}

const sourceClient = new MongoClient(sourceUri);
const targetClient = new MongoClient(targetUri);

function indexOptions(index) {
  const allowed = [
    'name',
    'unique',
    'sparse',
    'expireAfterSeconds',
    'partialFilterExpression',
    'collation',
    'hidden',
  ];
  return Object.fromEntries(allowed.filter((key) => index[key] !== undefined).map((key) => [key, index[key]]));
}

async function copyCollection(sourceDb, targetDb, collectionName, suffix) {
  const source = sourceDb.collection(collectionName);
  const target = targetDb.collection(collectionName);
  const sourceCount = await source.countDocuments({});
  const targetCount = await target.countDocuments({});

  if (targetCount > 0 && !replace) {
    throw new Error(`${collectionName}: destino possui ${targetCount} documentos; use --replace conscientemente.`);
  }

  const temporaryName = `__app_migration_${collectionName}_${suffix}`;
  const temporary = targetDb.collection(temporaryName);
  await temporary.drop().catch((error) => {
    if (error?.codeName !== 'NamespaceNotFound') throw error;
  });
  await targetDb.createCollection(temporaryName);

  let copied = 0;
  let batch = [];
  for await (const document of source.find({}).batchSize(500)) {
    batch.push(document);
    if (batch.length === 500) {
      await temporary.insertMany(batch, { ordered: false });
      copied += batch.length;
      batch = [];
    }
  }
  if (batch.length) {
    await temporary.insertMany(batch, { ordered: false });
    copied += batch.length;
  }

  const indexes = await source.listIndexes().toArray().catch((error) => {
    if (error?.codeName === 'NamespaceNotFound') return [];
    throw error;
  });
  for (const index of indexes) {
    if (index.name === '_id_') continue;
    await temporary.createIndex(index.key, indexOptions(index));
  }

  const verified = await temporary.countDocuments({});
  if (verified !== sourceCount || copied !== sourceCount) {
    throw new Error(`${collectionName}: origem=${sourceCount}, copiados=${copied}, verificados=${verified}.`);
  }

  await temporary.rename(collectionName, { dropTarget: true });
  console.log(`${collectionName}: ${verified} documentos e ${Math.max(0, indexes.length - 1)} indices.`);
}

try {
  await Promise.all([sourceClient.connect(), targetClient.connect()]);
  const sourceDb = sourceClient.db(sourceDbName);
  const targetDb = targetClient.db(targetDbName);
  await Promise.all([sourceDb.command({ ping: 1 }), targetDb.command({ ping: 1 })]);

  const suffix = Date.now().toString(36);
  for (const collectionName of COLLECTIONS) {
    await copyCollection(sourceDb, targetDb, collectionName, suffix);
  }
  console.log('Migracao das collections do app concluida. A collection history nao foi alterada.');
} finally {
  await Promise.allSettled([sourceClient.close(), targetClient.close()]);
}
