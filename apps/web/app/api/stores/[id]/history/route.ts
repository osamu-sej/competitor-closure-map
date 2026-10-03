import { NextResponse } from 'next/server';
import { getHistory } from '../../../../../lib/repository';
export const dynamic='force-dynamic';
export async function GET(_request:Request,{params}:{params:Promise<{id:string}>}) {
  const {id}=await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return NextResponse.json({error:'Invalid ID'},{status:400});
  try {return NextResponse.json({items:await getHistory(id)});}
  catch(error) {console.error(error);return NextResponse.json({error:'データを取得できません。'},{status:503});}
}
