import { MongoClient, Db, Collection } from 'mongodb';

const uri = process.env.MONGO_URL;
const dbName = process.env.MONGO_DB || 'roleta_db';

if (!uri) {
  throw new Error('MONGO_URL não definida no ambiente.');
}

// Reaproveita o client entre hot-reloads do Next em desenvolvimento
// para não esgotar conexões.
let clientPromise: Promise<MongoClient>;

declare global {
  // eslint-disable-next-line no-var
  var _mongoClientPromise: Promise<MongoClient> | undefined;
}

if (process.env.NODE_ENV === 'development') {
  if (!global._mongoClientPromise) {
    global._mongoClientPromise = new MongoClient(uri).connect();
  }
  clientPromise = global._mongoClientPromise;
} else {
  clientPromise = new MongoClient(uri).connect();
}

export async function getDb(): Promise<Db> {
  const client = await clientPromise;
  return client.db(dbName);
}

/** Documento de usuário guardado em app_users. */
export interface AppUser {
  email: string;
  lotogreenToken: string;
  tokenObtidoEm: Date;
  autoReconnect: boolean;
  /** Presente apenas quando autoReconnect = true. */
  encryptedPassword?: { iv: string; authTag: string; ciphertext: string };
  criadoEm: Date;
  atualizadoEm: Date;
  ultimoLogin: Date;
}

export async function getUsers(): Promise<Collection<AppUser>> {
  const db = await getDb();
  return db.collection<AppUser>('app_users');
}

/**
 * Últimos `limit` números de uma mesa (history), MAIS RECENTE PRIMEIRO.
 * `rouletteId` ex.: "pragmatic-auto-roulette".
 */
export async function getRecentNumbers(
  rouletteId: string,
  limit = 200,
): Promise<number[]> {
  const db = await getDb();
  const docs = await db
    .collection('history')
    .find({ roulette_id: rouletteId }, { projection: { value: 1, _id: 0 } })
    .sort({ timestamp: -1 })
    .limit(limit)
    .toArray();
  return docs
    .map((d) => d.value)
    .filter((v): v is number => typeof v === 'number');
}
