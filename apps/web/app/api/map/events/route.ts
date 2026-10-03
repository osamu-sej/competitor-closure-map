import { NextRequest, NextResponse } from 'next/server';
import { parseFilters } from '../../../../lib/filters';
import { listClosures } from '../../../../lib/repository';
export const dynamic='force-dynamic';
export async function GET(request:NextRequest) {
  if (!request.nextUrl.searchParams.has('bbox')) return NextResponse.json({error:'bbox is required'},{status:400});
  const filters=parseFilters(request.nextUrl.searchParams);
  if (!filters.bbox) return NextResponse.json({error:'Invalid bbox'},{status:400});
  try {return NextResponse.json(await listClosures(filters));}
  catch(error) {console.error(error);return NextResponse.json({error:'データを取得できません。'},{status:503});}
}
