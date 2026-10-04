import { NextRequest, NextResponse } from 'next/server';
import { parseMapViewport, parseStoreFilters } from '../../../../lib/store-filters';
import { listStoreMapPoints } from '../../../../lib/repository';

export const dynamic='force-dynamic';
export async function GET(request:NextRequest) {
  const viewport=parseMapViewport(request.nextUrl.searchParams);
  if(!viewport)return NextResponse.json({error:'有効なbboxとzoomを指定してください。'},{status:400});
  try{return NextResponse.json(await listStoreMapPoints(parseStoreFilters(request.nextUrl.searchParams),viewport.bbox,viewport.zoom));}
  catch(error){console.error(error);return NextResponse.json({error:'地図の実店舗データを取得できません。'},{status:503});}
}
