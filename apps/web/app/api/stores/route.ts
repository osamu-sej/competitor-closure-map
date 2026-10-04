import { NextRequest, NextResponse } from 'next/server';
import { parseStoreFilters } from '../../../lib/store-filters';
import { StoreFilterError } from '../../../lib/store-filters';
import { listCurrentStores } from '../../../lib/repository';

export const dynamic='force-dynamic';
export async function GET(request:NextRequest) {
  try{return NextResponse.json(await listCurrentStores(parseStoreFilters(request.nextUrl.searchParams)));}
  catch(error){if(error instanceof StoreFilterError)return NextResponse.json({error:error.message},{status:400});console.error(error);return NextResponse.json({error:'実店舗データを取得できません。'},{status:503});}
}
