import { NextRequest, NextResponse } from 'next/server';
import { health } from '../../../lib/repository';
import { prefectures } from '../../../lib/prefectures';
export const dynamic='force-dynamic';
export async function GET(request:NextRequest) {try {const selected=request.nextUrl.searchParams.get('prefecture')??'';return NextResponse.json(await health(prefectures.some(name=>name===selected)?selected:''));} catch(error) {console.error(error);return NextResponse.json({ok:false,error:'DB接続またはsnapshotがありません。'},{status:503});}}
