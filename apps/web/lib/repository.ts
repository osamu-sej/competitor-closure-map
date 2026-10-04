import 'server-only';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { Pool } from 'pg';
import type { Closure, Filters, Store } from './types';

const dbMode = process.env.DATA_MODE === 'database';
const pool = dbMode ? new Pool({connectionString:process.env.DATABASE_URL, max:4}) : null;
type State = {runs:Array<{status:string;finished_at:string}>;stores:Store[];observations:Array<Record<string,unknown>>;events:Array<Record<string,unknown>>;evidence:Array<Record<string,unknown>>};

async function fixtureState(): Promise<State> {
  const filename = path.resolve(process.cwd(), 'data/fixture-state.json');
  try {return JSON.parse(await readFile(filename, 'utf8')) as State;}
  catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    return JSON.parse(await readFile(path.resolve(process.cwd(), 'fixtures/demo_state.json'), 'utf8')) as State;
  }
}
function parseNumber(v:unknown): number|null { return v == null ? null : Number(v); }
function fixtureClosure(state:State, event:Record<string,unknown>):Closure {
  const store = state.stores.find(s=>s.id===event.store_id)!;
  const nearest = state.stores.find(s=>s.id===event.nearest_seven_store_id) ?? null;
  const obs = state.observations.find(o=>o.id===event.last_observation_id)!;
  return {id:String(event.id),store,nearest_seven:nearest,detected_at:String(event.detected_at),last_seen_at:String(event.last_seen_at),status:String(event.status),closure_date:event.closure_date as string|null,reason:event.reason as string|null,confidence:String(event.confidence),distance_m:parseNumber(event.distance_m),within_100m:Boolean(event.within_100m),last_observation:obs as Closure['last_observation'],evidence:state.evidence.filter(e=>e.closure_event_id===event.id) as Closure['evidence']};
}
function filtered(event:Closure, f:Filters):boolean {
  if (f.status === 'CLOSED_BOTH' ? !['CLOSED_CONFIRMED','CLOSED_SUSPECTED'].includes(event.status) : f.status !== 'ALL' && event.status !== f.status) return false;
  if (!f.brands.includes(event.store.brand_family)) return false;
  if (f.prefecture && event.store.prefecture !== f.prefecture) return false;
  if (event.distance_m == null || event.distance_m > f.distance) return false;
  if (f.municipality && !event.store.city.includes(f.municipality)) return false;
  const date = event.closure_date ?? event.detected_at.slice(0,10);
  if (f.from && date < f.from || f.to && date > f.to) return false;
  if (f.bbox && (event.store.lng < f.bbox[0] || event.store.lat < f.bbox[1] || event.store.lng > f.bbox[2] || event.store.lat > f.bbox[3])) return false;
  return true;
}
const projection = `select e.id,e.detected_at,e.last_seen_at,e.status,e.closure_date,e.reason,e.confidence,e.distance_m,e.within_100m,
  to_jsonb(s) - 'location' - 'normalized_name' - 'normalized_address' - 'source_store_id' as store,
  to_jsonb(n) - 'location' - 'normalized_name' - 'normalized_address' - 'source_store_id' as nearest_seven,
  to_jsonb(o) - 'raw_payload' - 'licenses' as last_observation
  from closure_events e join stores s on s.id=e.store_id
  left join stores n on n.id=e.nearest_seven_store_id join store_observations o on o.id=e.last_observation_id`;
export async function listClosures(f:Filters):Promise<{items:Closure[];total:number}> {
  if (!pool) {
    const state=await fixtureState();
    const all=state.events.map(e=>fixtureClosure(state,e)).filter(e=>filtered(e,f)).sort((a,b)=>b.detected_at.localeCompare(a.detected_at)||((a.distance_m??Infinity)-(b.distance_m??Infinity)));
    return {items:all.slice(f.page*100,(f.page+1)*100),total:all.length};
  }
  const values:unknown[]=[f.distance];
  const predicates=[`e.distance_m <= $1`];
  if (f.status === 'CLOSED_BOTH') predicates.push(`e.status in ('CLOSED_CONFIRMED','CLOSED_SUSPECTED')`);
  else if (f.status !== 'ALL') {values.push(f.status);predicates.push(`e.status = $${values.length}`);}
  values.push(f.brands);predicates.push(`s.brand_family = any($${values.length}::text[])`);
  if (f.prefecture) {values.push(f.prefecture);predicates.push(`s.prefecture = $${values.length}`);}
  if (f.municipality) {values.push(`%${f.municipality.replace(/[\\%_]/g,'\\$&')}%`);predicates.push(`s.city ilike $${values.length} escape '\\'`);}
  if (f.from) {values.push(f.from);predicates.push(`coalesce(e.closure_date,e.detected_at::date) >= $${values.length}::date`);}
  if (f.to) {values.push(f.to);predicates.push(`coalesce(e.closure_date,e.detected_at::date) <= $${values.length}::date`);}
  if (f.bbox) {values.push(...f.bbox);const n=values.length;predicates.push(`ST_Intersects(s.location::geometry, ST_MakeEnvelope($${n-3},$${n-2},$${n-1},$${n},4326))`);}
  const where=predicates.join(' and ');
  const count=await pool.query(`select count(*)::integer as total from closure_events e join stores s on s.id=e.store_id where ${where}`,values);
  values.push(f.page*100);
  const rows=await pool.query(`${projection} where ${where} order by e.detected_at desc,e.distance_m asc limit 100 offset $${values.length}`,values);
  return {items:rows.rows.map(row=>({...row,distance_m:parseNumber(row.distance_m),store:row.store,nearest_seven:row.nearest_seven,last_observation:row.last_observation})),total:count.rows[0].total};
}
export async function getClosure(id:string):Promise<Closure|null> {
  if (!pool) {const state=await fixtureState();const event=state.events.find(e=>e.id===id);return event?fixtureClosure(state,event):null;}
  const rows=await pool.query(`${projection} where e.id=$1`,[id]);
  if (!rows.rowCount) return null;
  const evidence=await pool.query('select id,evidence_type,title,source_ref,evidence_date,summary,supports_closure from event_evidence where closure_event_id=$1 order by coalesce(evidence_date,created_at::date) desc',[id]);
  return {...rows.rows[0],distance_m:parseNumber(rows.rows[0].distance_m),evidence:evidence.rows};
}
export async function getHistory(id:string) {
  if (!pool) {const state=await fixtureState();return state.observations.filter(o=>o.store_id===id).sort((a,b)=>String(b.observed_at).localeCompare(String(a.observed_at))).map(({raw_payload,licenses,...rest})=>rest);}
  const rows=await pool.query('select id,snapshot_run_id,source,source_store_id,observed_name,observed_address,lat,lng,source_category,source_business_type,attributions,observed_at from store_observations where store_id=$1 order by observed_at desc limit 100',[id]);
  return rows.rows;
}
export async function health(prefecture='') {
  if (!pool) {const state=await fixtureState();const stores=state.stores.filter(s=>s.current_presence==='PRESENT'&&(!prefecture||s.prefecture===prefecture));return {ok:true,mode:'fixture',db:'not configured',latest_snapshot:state.runs.filter(r=>r.status==='succeeded').at(-1)?.finished_at??null,snapshot_count:state.runs.length,prefecture_count:1,store_count:stores.length,brands:Object.fromEntries(['FAMILY_MART','LAWSON','SEVEN_ELEVEN'].map(family=>[family,stores.filter(s=>s.brand_family===family).length]))};}
  await pool.query('select 1');
  const condition=prefecture?' and prefecture=$1':'';
  const values=prefecture?[prefecture]:[];
  const result=await pool.query(`select max(finished_at) as latest_snapshot,count(*)::integer as snapshot_count,count(distinct prefecture)::integer as prefecture_count from snapshot_runs where status='succeeded'${condition}`,values);
  const stores=await pool.query(`select brand_family,count(*)::integer as count from stores where current_presence='PRESENT'${condition} group by brand_family`,values);
  const brands=Object.fromEntries(['FAMILY_MART','LAWSON','SEVEN_ELEVEN'].map(family=>[family,stores.rows.find(row=>row.brand_family===family)?.count??0]));
  return {ok:true,mode:'database',db:'connected',...result.rows[0],store_count:stores.rows.reduce((sum,row)=>sum+row.count,0),brands};
}
