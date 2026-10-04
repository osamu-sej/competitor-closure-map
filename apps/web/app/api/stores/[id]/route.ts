import { NextResponse } from 'next/server';
import { getCurrentStore } from '../../../../lib/repository';

export const dynamic='force-dynamic';
export async function GET(_request:Request,{params}:{params:Promise<{id:string}>}) {
  const {id}=await params;
  if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id))return NextResponse.json({error:'店舗IDが正しくありません。'},{status:400});
  try{const store=await getCurrentStore(id);return store?NextResponse.json(store):NextResponse.json({error:'店舗が見つかりません。'},{status:404});}
  catch(error){console.error(error);return NextResponse.json({error:'実店舗データを取得できません。'},{status:503});}
}
