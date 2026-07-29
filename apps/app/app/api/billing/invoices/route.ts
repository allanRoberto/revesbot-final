import { NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { listAutomationInvoices } from '@/lib/invoices';

export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: 'Não autenticado.' }, { status: 401 });
  }
  const invoices = await listAutomationInvoices(session.email);
  return NextResponse.json({ invoices });
}
