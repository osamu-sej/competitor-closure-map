import { NextResponse } from 'next/server';
import { getClosure } from '../../../../lib/repository';
export const dynamic='force-dynamic';
export async function GET(_request:Request,{params}:{params:Promise<{id:string}>}) {
  const {id}=await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) return NextResponse.json({error:'Invalid ID'},{status:400});
  try {const closure=await getClosure(id);return closure?NextResponse.json(closure):NextResponse.json({error:'Not found'},{status:404});}
  catch(error) {console.error(error);return NextResponse.json({error:'データを取得できません。'},{status:503});}
}
