import { MongoClient, Db, Collection } from 'mongodb';
import { DEFAULT_HOUSE } from './houses';

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

/** Documento de usuário guardado em app_users. Um doc por (email + casa). */
export interface AppUser {
  email: string;
  /** Casa de apostas deste vínculo (lotogreen, esportiva, bateu, …). */
  house?: string;
  /** Token da casa. Nome legado; serve para qualquer casa. */
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
 * Busca o vínculo do usuário para (email + casa).
 * Docs antigos (pré-multicasa) não têm `house` → tratados como a casa padrão.
 */
export async function findAppUser(
  email: string,
  house: string,
): Promise<AppUser | null> {
  const users = await getUsers();
  if (house === DEFAULT_HOUSE) {
    // Prioriza o doc da casa exata (token atual); só cai no doc legado (sem
    // campo house) se não existir um doc específico — senão um doc antigo sem
    // house pode "sombrear" o login fresco e devolver um token expirado.
    return (
      (await users.findOne({ email, house })) ??
      (await users.findOne({ email, house: { $exists: false } }))
    );
  }
  return users.findOne({ email, house });
}

/** Assinatura do usuário (app_subscriptions). Um doc por email. */
export interface AppSubscription {
  email: string;
  status: 'pending' | 'active' | 'expired';
  planId?: string;
  amountCents?: number;
  /** Referência do pedido atual (txid do PIX). */
  orderRef?: string;
  requestedAt?: Date;
  activatedAt?: Date;
  expiresAt?: Date;
  criadoEm: Date;
  atualizadoEm: Date;
}

export async function getSubscriptions(): Promise<Collection<AppSubscription>> {
  const db = await getDb();
  return db.collection<AppSubscription>('app_subscriptions');
}

export type AutomationRunStatus =
  | 'starting'
  | 'waiting_signal'
  | 'running'
  | 'payment_due'
  | 'completed'
  | 'error';

/** Uma execução do piloto automático vinculada ao usuário e à casa ativa. */
export interface AutomationRun {
  runId: string;
  email: string;
  house: string;
  /** Preenchidos quando a central despachar um sinal para uma mesa. */
  gameId?: string;
  rouletteId?: string;
  betSessionId?: string;
  status: AutomationRunStatus;
  stopReason?: 'target_reached' | 'max_loss' | 'time_limit' | 'user_stop' | 'error';
  errorMessage?: string;
  bankrollStartCents: number;
  targetRateBps: number;
  targetProfitCents: number;
  maxLossCents: number;
  chipValueCents: number;
  commissionBps: number;
  netProfitCents: number;
  totalStakeCents: number;
  totalPayoutCents: number;
  roundsSettled: number;
  commissionCents?: number;
  amountDueCents?: number;
  billingFinalizedAt?: Date;
  startedAt: Date;
  expiresAt?: Date;
  stoppedAt?: Date;
  criadoEm: Date;
  atualizadoEm: Date;
}

export interface AutomationBet {
  runId: string;
  source?: 'automatic';
  signalId?: string;
  executionId?: string;
  house?: string;
  rouletteId?: string;
  roundId: string;
  betsCents: Record<string, number>;
  totalStakeCents: number;
  winningNumber: number;
  payoutCents: number;
  netProfitCents: number;
  balanceBeforeCents?: number;
  balanceAfterCents?: number;
  settledAt: Date;
  criadoEm: Date;
}

export interface AutomationBillingAccount {
  email: string;
  status: 'clear' | 'payment_due' | 'awaiting_payment';
  outstandingCents: number;
  activeRunId?: string;
  atualizadoEm: Date;
  criadoEm: Date;
}

export interface CommissionPaymentOrder {
  orderId: string;
  email: string;
  /** A fatura é nossa; a PixGo representa apenas uma tentativa de pagamento. */
  invoiceId?: string;
  runId?: string;
  provider: 'pixgo';
  providerPaymentId: string;
  externalId: string;
  amountCents: number;
  status: 'pending' | 'completed' | 'expired' | 'refunded';
  qrCode?: string;
  qrImageUrl?: string;
  expiresAt?: Date;
  paidAt?: Date;
  criadoEm: Date;
  atualizadoEm: Date;
}

export type AutomationInvoiceStatus =
  | 'pending'
  | 'awaiting_payment'
  | 'paid'
  | 'canceled';

export interface AutomationInvoice {
  invoiceId: string;
  email: string;
  type: 'activation' | 'commission';
  description: string;
  amountCents: number;
  status: AutomationInvoiceStatus;
  runId?: string;
  netProfitCents?: number;
  commissionBps?: number;
  dueAt?: Date;
  paidAt?: Date;
  criadoEm: Date;
  atualizadoEm: Date;
}

export interface PaymentWebhookEvent {
  eventKey: string;
  provider: 'pixgo';
  event: string;
  providerPaymentId: string;
  externalId?: string;
  payload: Record<string, unknown>;
  recebidoEm: Date;
}

export async function getAutomationRuns(): Promise<Collection<AutomationRun>> {
  const db = await getDb();
  return db.collection<AutomationRun>('automation_runs');
}

export async function getAutomationBets(): Promise<Collection<AutomationBet>> {
  const db = await getDb();
  return db.collection<AutomationBet>('automation_bets');
}

export async function getAutomationBillingAccounts(): Promise<
  Collection<AutomationBillingAccount>
> {
  const db = await getDb();
  return db.collection<AutomationBillingAccount>('automation_billing_accounts');
}

export async function getCommissionPaymentOrders(): Promise<
  Collection<CommissionPaymentOrder>
> {
  const db = await getDb();
  return db.collection<CommissionPaymentOrder>('commission_payment_orders');
}

export async function getAutomationInvoices(): Promise<
  Collection<AutomationInvoice>
> {
  const db = await getDb();
  return db.collection<AutomationInvoice>('automation_invoices');
}

export async function getPaymentWebhookEvents(): Promise<
  Collection<PaymentWebhookEvent>
> {
  const db = await getDb();
  return db.collection<PaymentWebhookEvent>('payment_webhook_events');
}

let automationIndexesPromise: Promise<void> | null = null;

/** Índices idempotentes para impedir rodadas, cobranças e webhooks duplicados. */
export function ensureAutomationIndexes(): Promise<void> {
  if (!automationIndexesPromise) {
    automationIndexesPromise = (async () => {
      const [runs, bets, billing, invoices, orders, events] = await Promise.all([
        getAutomationRuns(),
        getAutomationBets(),
        getAutomationBillingAccounts(),
        getAutomationInvoices(),
        getCommissionPaymentOrders(),
        getPaymentWebhookEvents(),
      ]);
      await Promise.all([
        runs.createIndex({ runId: 1 }, { unique: true }),
        runs.createIndex({ email: 1, house: 1, status: 1 }),
        bets.createIndex({ runId: 1, roundId: 1 }, { unique: true }),
        bets.createIndex(
          { runId: 1, signalId: 1 },
          {
            unique: true,
            partialFilterExpression: { signalId: { $type: 'string' } },
          },
        ),
        billing.createIndex({ email: 1 }, { unique: true }),
        invoices.createIndex({ invoiceId: 1 }, { unique: true }),
        invoices.createIndex({ email: 1, status: 1, criadoEm: -1 }),
        invoices.createIndex(
          { email: 1, type: 1 },
          {
            unique: true,
            partialFilterExpression: { type: 'activation' },
          },
        ),
        orders.createIndex({ orderId: 1 }, { unique: true }),
        orders.createIndex({ providerPaymentId: 1 }, { unique: true }),
        orders.createIndex({ externalId: 1 }, { unique: true }),
        events.createIndex({ eventKey: 1 }, { unique: true }),
      ]);
    })().catch((error) => {
      automationIndexesPromise = null;
      throw error;
    });
  }
  return automationIndexesPromise;
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
