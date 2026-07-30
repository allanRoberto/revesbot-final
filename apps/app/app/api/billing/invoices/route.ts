import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import {
  listAutomationInvoices,
  reconcilePendingPixGoPayments,
} from '@/lib/invoices';

export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }
  await reconcilePendingPixGoPayments(session.email);
  const invoices = await listAutomationInvoices(session.email);
  return NextResponse.json({ invoices });
}
