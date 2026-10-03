import { NextRequest, NextResponse } from 'next/server';
import { parseFilters } from '../../../lib/filters';
import { listClosures } from '../../../lib/repository';
export const dynamic='force-dynamic';
export async function GET(request:NextRequest) {
  try { return NextResponse.json(await listClosures(parseFilters(request.nextUrl.searchParams))); }
  catch (error) { console.error(error); return NextResponse.json({error:'データを取得できません。snapshotまたはDB接続を確認してください。'}, {status:503}); }
}
