import { NextResponse } from 'next/server';
import { health } from '../../../lib/repository';
export const dynamic='force-dynamic';
export async function GET() {try {return NextResponse.json(await health());} catch(error) {console.error(error);return NextResponse.json({ok:false,error:'DB接続またはsnapshotがありません。'},{status:503});}}
