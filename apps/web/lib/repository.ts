import 'server-only';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { Pool } from 'pg';
import type { Closure, Filters, Store, StoreMapPoint } from './types';
import type { StoreFilters } from './store-filters';
import { addLawsonVariantCount, emptyLawsonVariantCounts } from './lawson-variant';
import { changeFromRow, forEachSheetRow, getSmallSheetTab, storeFromRow, type SheetChange, type SheetRow, type SheetRun } from './sheets-reader';

const dbMode = process.env.DATA_MODE === 'database';
const sheetMode = process.env.DATA_MODE === 'sheets';
const pool = dbMode ? new Pool({connectionString:process.env.DATABASE_URL, max:4}) : null;
const lawsonOfficialBenchmark = {count:14630,as_of:'2026-08-31',source:'https://www.lawson.co.jp/company/ir/financial/monthly/index.html'};
type State = {runs:Array<{status:string;finished_at:string;prefecture?:string}>;stores:Store[];observations:Array<Record<string,unknown>>;events:Array<Record<string,unknown>>;evidence:Array<Record<string,unknown>>;changes?:Array<Record<string,unknown>>};

async function fixtureState(): Promise<State> {
  const filename = path.resolve(process.cwd(), 'data/fixture-state.json');
  try {return JSON.parse(await readFile(filename, 'utf8')) as State;}
  catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    return JSON.parse(await readFile(path.resolve(process.cwd(), 'fixtures/demo_state.json'), 'utf8')) as State;
  }
}
async function sourceState():Promise<State> { return fixtureState(); }
function parseNumber(v:unknown): number|null { return v == null ? null : Number(v); }
function escapeLike(value:string) {return `%${value.replace(/[\\%_]/g,'\\$&')}%`;}
function historical(filters:StoreFilters):boolean {return Boolean(filters.from||filters.to);}
function observationDay(value:string):string {return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));}
const storeOrder=(a:Store,b:Store)=>a.prefecture.localeCompare(b.prefecture,'ja')||a.city.localeCompare(b.city,'ja')||a.canonical_name.localeCompare(b.canonical_name,'ja')||a.id.localeCompare(b.id,'ja');
function keepSmallest(heap:Store[],store:Store,capacity:number) {
  if(heap.length<capacity){
    let index=heap.push(store)-1;
    while(index>0){const parent=(index-1)>>1;if(storeOrder(heap[parent],heap[index])>=0)break;[heap[parent],heap[index]]=[heap[index],heap[parent]];index=parent;}
    return;
  }
  if(storeOrder(store,heap[0])>=0)return;
  heap[0]=store;let index=0;
  while(true){const left=index*2+1,right=left+1;let largest=index;
    if(left<heap.length&&storeOrder(heap[left],heap[largest])>0)largest=left;
    if(right<heap.length&&storeOrder(heap[right],heap[largest])>0)largest=right;
    if(largest===index)break;[heap[index],heap[largest]]=[heap[largest],heap[index]];index=largest;
  }
}
function matchesStore(store:Store,filters:StoreFilters) {
  return filters.brands.includes(store.brand_family)&&(!filters.prefecture||store.prefecture===filters.prefecture)
    &&(!filters.municipality||store.city.includes(filters.municipality))&&(!filters.q||`${store.canonical_name} ${store.address}`.includes(filters.q));
}
type SelectedChange=Pick<SheetChange,'observed_name'|'observed_address'|'lat'|'lng'|'observed_at'>;
type HistoryState={active:boolean;matched:boolean;selected?:SelectedChange};
async function sheetHistory(filters:StoreFilters):Promise<Map<string,HistoryState>> {
  const from=filters.from?new Date(`${filters.from}T00:00:00+09:00`).getTime():Number.NEGATIVE_INFINITY;
  const to=filters.to?new Date(`${filters.to}T23:59:59.999+09:00`).getTime():Number.POSITIVE_INFINITY;
  const history=new Map<string,HistoryState>();
  await forEachSheetRow('Changes','N',row=>{
    const storeId=String(row[1]??'');const observedAt=String(row[2]??'');const changeType=String(row[3]??'');const time=new Date(observedAt).getTime();
    if(time>to)return;
    let state=history.get(storeId);
    if(!state){state={active:false,matched:false};history.set(storeId,state);}
    if(['BASELINE','NEW_STORE','REOPENED'].includes(changeType)){
      state.active=true;state.selected={observed_name:String(row[5]??''),observed_address:String(row[6]??''),lat:Number(row[9]??0),lng:Number(row[10]??0),observed_at:observedAt};
      if(time>=from)state.matched=true;
    } else if(changeType==='STORE_UPDATED'&&state.active){
      state.selected={observed_name:String(row[5]??''),observed_address:String(row[6]??''),lat:Number(row[9]??0),lng:Number(row[10]??0),observed_at:observedAt};
      if(time>=from)state.matched=true;
    } else if(changeType==='MISSING'){
      if(state.active&&time>=from)state.matched=true;
      state.active=false;
    }
  });
  for(const state of history.values())if(state.active)state.matched=true;
  return history;
}
async function listSheetsStores(filters:StoreFilters):Promise<{items:Store[];total:number}> {
  if(!filters.brands.length)return {items:[],total:0};
  const past=historical(filters);const states=past?await sheetHistory(filters):null;
  const capacity=(filters.page+1)*100;const heap:Store[]=[];let total=0;
  await forEachSheetRow('Stores','V',row=>{
    const store=storeFromRow(row,past);
    if(!store.id)return;
    let candidate:Store|undefined;
    if(past){
      const state=states!.get(store.id);
      if(state?.matched){const change=state.selected;candidate={...store,...(change?{canonical_name:change.observed_name||store.canonical_name,address:change.observed_address||store.address,lat:change.lat,lng:change.lng,observed_at:change.observed_at}:{observed_at:store.last_seen_at})};}
    }else if(store.current_presence==='PRESENT')candidate=store;
    if(candidate&&store.current_presence!=='SUPPRESSED'&&matchesStore(candidate,filters)){total++;keepSmallest(heap,candidate,capacity);}
  });
  heap.sort(storeOrder);
  return {items:heap.slice(filters.page*100,(filters.page+1)*100),total};
}
async function storeByIdInSheets(id:string,filters:StoreFilters):Promise<Store|null> {
  const states=historical(filters)?await sheetHistory(filters):null;let found:Store|null=null;
  await forEachSheetRow('Stores','V',row=>{
    if(String(row[0]??'')!==id)return;
    const base=storeFromRow(row,Boolean(states));
    if(states){const state=states.get(id);if(!state?.matched||base.current_presence==='SUPPRESSED')return;const change=state.selected;found={...base,...(change?{canonical_name:change.observed_name||base.canonical_name,address:change.observed_address||base.address,lat:change.lat,lng:change.lng,observed_at:change.observed_at}:{observed_at:base.last_seen_at})};}
    else if(base.current_presence==='PRESENT')found=base;
    return false;
  });
  return found&&matchesStore(found,filters)?found:null;
}
type MapAggregate={count:number;brand:string;lat:number;lng:number;id:string|null;name:string|null};
function addMapStore(groups:Map<string,MapAggregate>,store:Store,step:number) {
  const key=`${Math.floor(store.lng/step)}:${Math.floor(store.lat/step)}`;const current=groups.get(key);
  if(!current){groups.set(key,{count:1,brand:store.brand_family,lat:store.lat,lng:store.lng,id:store.id,name:store.canonical_name});return;}
  current.count++;current.lat+=store.lat;current.lng+=store.lng;if(current.brand!==store.brand_family)current.brand='MIXED';current.id=null;current.name=null;
}
function fixtureStores(state:State, filters:StoreFilters):Store[] {
  const changesByStore=new Map<string,Array<Record<string,unknown>>>();
  for(const change of state.changes??[]){const id=String(change.store_id);const rows=changesByStore.get(id)??[];rows.push(change);changesByStore.set(id,rows);}
  const candidates=historical(filters)&&state.changes?[...state.stores].flatMap(store=>{
    const timeline=(changesByStore.get(store.id)??[]).sort((a,b)=>String(a.observed_at).localeCompare(String(b.observed_at)));
    const from=filters.from?new Date(`${filters.from}T00:00:00+09:00`).getTime():Number.NEGATIVE_INFINITY;
    const to=filters.to?new Date(`${filters.to}T23:59:59.999+09:00`).getTime():Number.POSITIVE_INFINITY;
    let activeAt:number|undefined;
    let matchedChange:Record<string,unknown>|undefined;
    let matched=false;
    const initial=store as Store & {first_seen_at?:string;last_seen_at?:string};
    activeAt=initial.first_seen_at?new Date(initial.first_seen_at).getTime():undefined;
    for(const change of timeline){
      const time=new Date(String(change.observed_at)).getTime();
      if(['BASELINE','NEW_STORE','REOPENED'].includes(String(change.change_type))){activeAt=time;matchedChange=change;}
      else if(change.change_type==='STORE_UPDATED'&&activeAt!==undefined&&time<=to)matchedChange=change;
      else if(change.change_type==='MISSING'){
        if(activeAt!==undefined&&activeAt<=to&&time>=from)matched=true;
        activeAt=undefined;
      }
      if(activeAt!==undefined&&activeAt<=to&&(!Number.isFinite(to)||time<=to))matchedChange=change.change_type==='STORE_UPDATED'?change:matchedChange;
    }
    if(activeAt!==undefined&&activeAt<=to)matched=true;
    if(!matched)return [];
    const change=matchedChange;
    return [{...store,...(change?{canonical_name:String(change.observed_name||store.canonical_name),address:String(change.observed_address||store.address),lat:Number(change.lat??store.lat),lng:Number(change.lng??store.lng)}:{}),observed_at:String(change?.observed_at??initial.last_seen_at??store.observed_at??'')}];
  }):historical(filters)?[...state.observations]
    .filter(o=>{const day=observationDay(String(o.observed_at));return (!filters.from||day>=filters.from)&&(!filters.to||day<=filters.to);})
    .sort((a,b)=>String(b.observed_at).localeCompare(String(a.observed_at)))
    .reduce((found,observation)=>{
      const id=String(observation.store_id);
      if(!found.has(id)){
        const store=state.stores.find(item=>item.id===id);
        if(store)found.set(id,{...store,canonical_name:String(observation.observed_name),address:String(observation.observed_address),lat:Number(observation.lat),lng:Number(observation.lng),observed_at:String(observation.observed_at)});
      }
      return found;
    },new Map<string,Store>()):null;
  return (candidates?[...candidates.values()].filter(store=>store.current_presence!=='SUPPRESSED'):state.stores.filter(store=>store.current_presence==='PRESENT')).filter(store=>
    filters.brands.includes(store.brand_family)
    &&(!filters.prefecture||store.prefecture===filters.prefecture)
    &&(!filters.municipality||store.city.includes(filters.municipality))
    &&(!filters.q||`${store.canonical_name} ${store.address}`.includes(filters.q)))
    .sort((a,b)=>a.prefecture.localeCompare(b.prefecture,'ja')||a.city.localeCompare(b.city,'ja')||a.canonical_name.localeCompare(b.canonical_name,'ja'));
}
function storeScope(filters:StoreFilters,values:unknown[]) {
  const past=historical(filters);
  let cte='';
  let from='stores s';
  let name='s.canonical_name',address='s.address',lat='s.lat',lng='s.lng';
  if(past){
    const dates:string[]=[];
    if(filters.from){values.push(filters.from);dates.push(`o.observed_at >= ($${values.length}::date::timestamp at time zone 'Asia/Tokyo')`);}
    if(filters.to){values.push(filters.to);dates.push(`o.observed_at < (($${values.length}::date + 1)::timestamp at time zone 'Asia/Tokyo')`);}
    cte=`with observed as (select distinct on (o.store_id) o.store_id,o.observed_name,o.observed_address,o.lat,o.lng,o.observed_at from store_observations o where ${dates.join(' and ')} order by o.store_id,o.observed_at desc,o.id desc)`;
    from='stores s join observed o on o.store_id=s.id';
    name='o.observed_name';address='o.observed_address';lat='o.lat';lng='o.lng';
  }
  const predicates=[`s.brand_family=any($1::text[])`];
  if(!past)predicates.push(`s.current_presence='PRESENT'`);
  if(filters.prefecture){values.push(filters.prefecture);predicates.push(`s.prefecture=$${values.length}`);}
  if(filters.municipality){values.push(escapeLike(filters.municipality));predicates.push(`s.city ilike $${values.length} escape '\\'`);}
  if(filters.q){values.push(escapeLike(filters.q));predicates.push(`(${name} ilike $${values.length} escape '\\' or ${address} ilike $${values.length} escape '\\')`);}
  return {cte,from,name,address,lat,lng,predicates,past};
}
export async function listCurrentStores(filters:StoreFilters):Promise<{items:Store[];total:number}> {
  if(!filters.brands.length)return {items:[],total:0};
  if(sheetMode)return listSheetsStores(filters);
  if(!pool){const all=fixtureStores(await sourceState(),filters);return {items:all.slice(filters.page*100,(filters.page+1)*100),total:all.length};}
  const values:unknown[]=[filters.brands];
  const scope=storeScope(filters,values);
  const where=scope.predicates.join(' and ');
  const count=await pool.query(`${scope.cte} select count(*)::integer as total from ${scope.from} where ${where}`,values);
  values.push(filters.page*100);
  const rows=await pool.query(`${scope.cte} select s.id,s.brand_family,${scope.name} as canonical_name,${scope.address} as address,s.prefecture,s.city,${scope.lat} as lat,${scope.lng} as lng,s.current_presence${scope.past?',o.observed_at':''} from ${scope.from} where ${where} order by s.prefecture,s.city,${scope.name},s.id limit 100 offset $${values.length}`,values);
  return {items:rows.rows,total:count.rows[0].total};
}
export async function getStore(id:string,filters:StoreFilters):Promise<Store|null> {
  if(sheetMode)return storeByIdInSheets(id,filters);
  if(!pool)return fixtureStores(await sourceState(),filters).find(store=>store.id===id)??null;
  const values:unknown[]=[filters.brands];
  const scope=storeScope(filters,values);
  values.push(id);
  const rows=await pool.query(`${scope.cte} select s.id,s.brand_family,${scope.name} as canonical_name,${scope.address} as address,s.prefecture,s.city,${scope.lat} as lat,${scope.lng} as lng,s.current_presence${scope.past?',o.observed_at':''} from ${scope.from} where ${scope.predicates.join(' and ')} and s.id=$${values.length}`,values);
  return rows.rows[0]??null;
}
export async function listStoreMapPoints(filters:StoreFilters,bbox:[number,number,number,number],zoom:number):Promise<{points:StoreMapPoint[];truncated:boolean}> {
  if(!filters.brands.length)return {points:[],truncated:false};
  const step=Math.max(0.00005,360/2**zoom*80/512);
  if(sheetMode){
    const past=historical(filters);const states=past?await sheetHistory(filters):null;
    const groups=new Map<string,MapAggregate>();
    await forEachSheetRow('Stores','V',row=>{
      const store=storeFromRow(row,past);if(!store.id)return;
      let candidate:Store|undefined;
      if(past){const state=states!.get(store.id);if(state?.matched&&store.current_presence!=='SUPPRESSED'){const change=state.selected;candidate={...store,...(change?{canonical_name:change.observed_name||store.canonical_name,address:change.observed_address||store.address,lat:change.lat,lng:change.lng,observed_at:change.observed_at}:{observed_at:store.last_seen_at})};}}
      else if(store.current_presence==='PRESENT')candidate=store;
      if(candidate&&matchesStore(candidate,filters)&&candidate.lng>=bbox[0]&&candidate.lat>=bbox[1]&&candidate.lng<=bbox[2]&&candidate.lat<=bbox[3])addMapStore(groups,candidate,step);
    });
    const points=[...groups.values()].map(group=>({brand_family:group.brand,count:group.count,lat:group.lat/group.count,lng:group.lng/group.count,id:group.id,canonical_name:group.name}));
    points.sort((a,b)=>b.count-a.count);
    return {points:points.slice(0,1200),truncated:points.length>1200};
  }
  if(!pool){
    const stores=fixtureStores(await sourceState(),filters)
      .filter(store=>store.lng>=bbox[0]&&store.lat>=bbox[1]&&store.lng<=bbox[2]&&store.lat<=bbox[3]);
    const grouped=new Map<string,MapAggregate>();
    for(const store of stores)addMapStore(grouped,store,step);
    const points=[...grouped.values()].map(group=>({brand_family:group.brand,count:group.count,lat:group.lat/group.count,lng:group.lng/group.count,id:group.id,canonical_name:group.name}));
    points.sort((a,b)=>b.count-a.count);
    return {points:points.slice(0,1200),truncated:points.length>1200};
  }
  const values:unknown[]=[filters.brands];
  const scope=storeScope(filters,values);
  values.push(...bbox);const [west,south,east,north]=[values.length-3,values.length-2,values.length-1,values.length];
  values.push(step);const grid=values.length;
  const rows=await pool.query(`${scope.cte?`${scope.cte},`:'with'} visible as (
      select s.id,s.brand_family,${scope.name} as canonical_name,${scope.lat} as lat,${scope.lng} as lng,floor(${scope.lng}/$${grid}::double precision) as x,floor(${scope.lat}/$${grid}::double precision) as y
      from ${scope.from} where ${scope.predicates.join(' and ')}
        and ${scope.lng} between $${west} and $${east} and ${scope.lat} between $${south} and $${north}
    ) select case when count(distinct brand_family)=1 then min(brand_family) else 'MIXED' end as brand_family,
      avg(lat)::double precision as lat,avg(lng)::double precision as lng,
      count(*)::integer as count,case when count(*)=1 then min(id::text) else null end as id,
      case when count(*)=1 then min(canonical_name) else null end as canonical_name
      from visible group by x,y order by count desc limit 1201`,values);
  return {points:rows.rows.slice(0,1200),truncated:rows.rows.length>1200};
}
function fixtureClosure(state:State, event:Record<string,unknown>):Closure {
  const store = state.stores.find(s=>s.id===event.store_id)!;
  const nearest = state.stores.find(s=>s.id===event.nearest_seven_store_id) ?? null;
  const obs = state.observations.find(o=>o.id===event.last_observation_id)!;
  return {id:String(event.id),store,nearest_seven:nearest,detected_at:String(event.detected_at),last_seen_at:String(event.last_seen_at),status:String(event.status),closure_date:event.closure_date as string|null,reason:event.reason as string|null,confidence:String(event.confidence),distance_m:parseNumber(event.distance_m),within_100m:Boolean(event.within_100m),last_observation:obs as Closure['last_observation'],evidence:state.evidence.filter(e=>e.closure_event_id===event.id) as Closure['evidence']};
}
function filtered(event:Closure, f:Filters):boolean {
  if(event.status==='OUT_OF_SCOPE')return false;
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
async function materializeSheetClosures(events:Record<string,unknown>[]):Promise<Closure[]> {
  if(!events.length)return [];
  const storeIds=new Set<string>();
  for(const event of events){storeIds.add(String(event.store_id));if(event.nearest_seven_store_id)storeIds.add(String(event.nearest_seven_store_id));}
  const stores=new Map<string,Store>();
  await forEachSheetRow('Stores','V',row=>{
    const id=String(row[0]??'');
    if(storeIds.has(id))stores.set(id,storeFromRow(row));
    if(stores.size===storeIds.size)return false;
  });
  const evidence=await getSmallSheetTab('Evidence');
  return events.flatMap(event=>{
    const store=stores.get(String(event.store_id));if(!store)return [];
    const nearest=event.nearest_seven_store_id?stores.get(String(event.nearest_seven_store_id))??null:null;
    const lastObservation={id:String(event.last_observation_id),store_id:store.id,observed_name:store.canonical_name,observed_address:store.address,lat:store.lat,lng:store.lng,source:store.source??'openpoi',source_category:store.source_category??null,source_business_type:store.source_business_type??null,observed_at:String(event.last_seen_at),licenses:store.licenses??[],attributions:store.attributions??[]} as Closure['last_observation'];
    return [{...event,distance_m:parseNumber(event.distance_m),within_100m:Boolean(event.within_100m),store,nearest_seven:nearest,last_observation:lastObservation,
      evidence:evidence.filter(row=>row.closure_event_id===event.id)} as unknown as Closure];
  });
}
const projection = `select e.id,e.detected_at,e.last_seen_at,e.status,e.closure_date,e.reason,e.confidence,e.distance_m,e.within_100m,
  to_jsonb(s) - 'location' - 'normalized_name' - 'normalized_address' - 'source_store_id' as store,
  to_jsonb(n) - 'location' - 'normalized_name' - 'normalized_address' - 'source_store_id' as nearest_seven,
  to_jsonb(o) - 'raw_payload' - 'licenses' as last_observation
  from closure_events e join stores s on s.id=e.store_id
  left join stores n on n.id=e.nearest_seven_store_id join store_observations o on o.id=e.last_observation_id`;
export async function listClosures(f:Filters):Promise<{items:Closure[];total:number}> {
  if(sheetMode){
    const events=await getSmallSheetTab('ClosureEvents');
    const relevant=events.filter(event=>{
      if(event.status==='OUT_OF_SCOPE')return false;
      if(f.status==='CLOSED_BOTH'?!['CLOSED_CONFIRMED','CLOSED_SUSPECTED'].includes(String(event.status)):f.status!=='ALL'&&event.status!==f.status)return false;
      if(event.distance_m==null||Number(event.distance_m)>f.distance)return false;
      const date=String(event.closure_date??event.detected_at).slice(0,10);
      if(f.from&&date<f.from||f.to&&date>f.to)return false;
      return true;
    });
    if(!relevant.length)return {items:[],total:0};
    const all=(await materializeSheetClosures(relevant)).filter(event=>filtered(event,f))
      .sort((a,b)=>b.detected_at.localeCompare(a.detected_at)||((a.distance_m??Infinity)-(b.distance_m??Infinity)));
    return {items:all.slice(f.page*100,(f.page+1)*100),total:all.length};
  }
  if (!pool) {
    const state=await sourceState();
    const all=state.events.map(e=>fixtureClosure(state,e)).filter(e=>filtered(e,f)).sort((a,b)=>b.detected_at.localeCompare(a.detected_at)||((a.distance_m??Infinity)-(b.distance_m??Infinity)));
    return {items:all.slice(f.page*100,(f.page+1)*100),total:all.length};
  }
  const values:unknown[]=[f.distance];
  const predicates=[`e.distance_m <= $1`,`e.status <> 'OUT_OF_SCOPE'`];
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
  if(sheetMode){const events=await getSmallSheetTab('ClosureEvents');const event=events.find(row=>row.id===id);if(!event||event.status==='OUT_OF_SCOPE')return null;return (await materializeSheetClosures([event]))[0]??null;}
  if (!pool) {const state=await sourceState();const event=state.events.find(e=>e.id===id);return event&&event.status!=='OUT_OF_SCOPE'?fixtureClosure(state,event):null;}
  const rows=await pool.query(`${projection} where e.id=$1 and e.status <> 'OUT_OF_SCOPE'`,[id]);
  if (!rows.rowCount) return null;
  const evidence=await pool.query('select id,evidence_type,title,source_ref,evidence_date,summary,supports_closure from event_evidence where closure_event_id=$1 order by coalesce(evidence_date,created_at::date) desc',[id]);
  return {...rows.rows[0],distance_m:parseNumber(rows.rows[0].distance_m),evidence:evidence.rows};
}
export async function getHistory(id:string) {
  if(sheetMode){
    const items:SheetChange[]=[];
    await forEachSheetRow('Changes','N',row=>{const change=changeFromRow(row);if(change.store_id===id)items.push(change);});
    return items.sort((a,b)=>b.observed_at.localeCompare(a.observed_at)).slice(0,100);
  }
  if (!pool) {const state=await sourceState();if(state.changes)return state.changes.filter(change=>change.store_id===id).sort((a,b)=>String(b.observed_at).localeCompare(String(a.observed_at)));return state.observations.filter(o=>o.store_id===id).sort((a,b)=>String(b.observed_at).localeCompare(String(a.observed_at))).map(({raw_payload,licenses,...rest})=>rest);}
  const rows=await pool.query('select id,snapshot_run_id,source,source_store_id,observed_name,observed_address,lat,lng,source_category,source_business_type,attributions,observed_at from store_observations where store_id=$1 order by observed_at desc limit 100',[id]);
  return rows.rows;
}
const sheetHealthCache=new Map<string,{expiresAt:number;value:Record<string,unknown>}>();
async function sheetExtent(prefecture:string):Promise<{west:number;south:number;east:number;north:number}|null> {
  if(!prefecture)return {west:122,south:20,east:154.5,north:46.1};
  const latitudes:number[]=[],longitudes:number[]=[];
  await forEachSheetRow('Stores','I',row=>{
    if(String(row[4]??'')!==prefecture||String(row[8]??'PRESENT')!=='PRESENT')return;
    const lat=Number(row[6]),lng=Number(row[7]);if(Number.isFinite(lat)&&Number.isFinite(lng)){latitudes.push(lat);longitudes.push(lng);}
  });
  if(!latitudes.length)return null;
  latitudes.sort((a,b)=>a-b);longitudes.sort((a,b)=>a-b);
  const low=Math.floor((latitudes.length-1)*0.01),high=Math.ceil((latitudes.length-1)*0.99);
  return {west:longitudes[low],south:latitudes[low],east:longitudes[high],north:latitudes[high]};
}
async function sheetsHealth(prefecture:string):Promise<Record<string,unknown>> {
  const cached=sheetHealthCache.get(prefecture);if(cached&&cached.expiresAt>Date.now())return cached.value;
  const runs=(await getSmallSheetTab('SnapshotRuns') as SheetRun[]).filter(run=>run.status==='succeeded'&&(!prefecture||run.prefecture===prefecture));
  const latestByPrefecture=new Map<string,SheetRun>();
  for(const run of runs){const current=latestByPrefecture.get(run.prefecture);if(!current||run.finished_at>current.finished_at)latestByPrefecture.set(run.prefecture,run);}
  const latest=[...latestByPrefecture.values()];
  const families=['FAMILY_MART','LAWSON','SEVEN_ELEVEN'];
  const brands=Object.fromEntries(families.map(family=>[family,latest.reduce((sum,run)=>sum+Number((run.metadata.families as Record<string,unknown>|undefined)?.[family]??0),0)]));
  const storeCount=latest.reduce((sum,run)=>sum+run.store_count,0);
  const [extent,lawsonVariants]=await Promise.all([sheetExtent(prefecture),sheetLawsonVariantCounts(prefecture)]);
  const value={ok:true,mode:'sheets',db:'connected',first_snapshot:runs.length?runs.reduce((old,run)=>run.started_at&&run.started_at<old?run.started_at:old,runs[0].started_at):null,
    latest_snapshot:runs.length?runs.reduce((latest,run)=>run.finished_at>latest?run.finished_at:latest,runs[0].finished_at):null,
    snapshot_day_count:new Set(runs.map(run=>observationDay(run.finished_at))).size,snapshot_count:runs.length,
    prefecture_count:new Set(runs.map(run=>run.prefecture).filter(Boolean)).size,store_count:storeCount,brands,lawson_variants:lawsonVariants,lawson_official_count:lawsonOfficialBenchmark.count,lawson_official_as_of:lawsonOfficialBenchmark.as_of,lawson_official_source:lawsonOfficialBenchmark.source,scope_prefecture:prefecture,extent};
  sheetHealthCache.set(prefecture,{value,expiresAt:Date.now()+30000});
  return value;
}
async function sheetLawsonVariantCounts(prefecture:string):Promise<Record<string,number>> {
  const counts=emptyLawsonVariantCounts();
  await forEachSheetRow('Stores','I',row=>{
    if(String(row[1]??'')!=='LAWSON'||String(row[8]??'PRESENT')!=='PRESENT')return;
    if(prefecture&&String(row[4]??'')!==prefecture)return;
    addLawsonVariantCount(counts,String(row[2]??''));
  });
  return counts;
}
export async function health(prefecture='') {
  if(sheetMode)return sheetsHealth(prefecture);
  if (!pool) {
    const state=await sourceState();
    const stores=state.stores.filter(s=>s.current_presence==='PRESENT'&&(!prefecture||s.prefecture===prefecture));
    const runs=state.runs.filter(r=>r.status==='succeeded'&&(!prefecture||r.prefecture===prefecture));
    const brands=Object.fromEntries(['FAMILY_MART','LAWSON','SEVEN_ELEVEN'].map(family=>[family,stores.filter(s=>s.brand_family===family).length]));
    const lawsonVariants=emptyLawsonVariantCounts();
    for(const store of stores)if(store.brand_family==='LAWSON')addLawsonVariantCount(lawsonVariants,store.canonical_name);
    const isSheets=sheetMode;
    return {ok:true,mode:isSheets?'sheets':'fixture',db:isSheets?'connected':'not configured',first_snapshot:runs[0]?.finished_at??null,latest_snapshot:runs.at(-1)?.finished_at??null,snapshot_day_count:new Set(runs.map(r=>observationDay(r.finished_at))).size,snapshot_count:runs.length,prefecture_count:isSheets?new Set(runs.map(r=>r.prefecture)).size:1,store_count:stores.length,brands,lawson_variants:lawsonVariants,lawson_official_count:lawsonOfficialBenchmark.count,lawson_official_as_of:lawsonOfficialBenchmark.as_of,lawson_official_source:lawsonOfficialBenchmark.source,scope_prefecture:prefecture,extent:stores.length?{west:Math.min(...stores.map(s=>s.lng)),south:Math.min(...stores.map(s=>s.lat)),east:Math.max(...stores.map(s=>s.lng)),north:Math.max(...stores.map(s=>s.lat))}:null};
  }
  await pool.query('select 1');
  const condition=prefecture?' and prefecture=$1':'';
  const values=prefecture?[prefecture]:[];
  const result=await pool.query(`select min(started_at) as first_snapshot,max(finished_at) as latest_snapshot,count(distinct (started_at at time zone 'Asia/Tokyo')::date)::integer as snapshot_day_count,count(*)::integer as snapshot_count,count(distinct prefecture)::integer as prefecture_count from snapshot_runs where status='succeeded'${condition}`,values);
  const stores=await pool.query(`select brand_family,count(*)::integer as count from stores where current_presence='PRESENT'${condition} group by brand_family`,values);
  const lawsonNames=await pool.query(`select canonical_name,count(*)::integer as count from stores where brand_family='LAWSON' and current_presence='PRESENT'${condition} group by canonical_name`,values);
  // Source prefecture labels can contain a few coordinates far outside the
  // prefecture. Fit the common footprint instead of one erroneous POI.
  const bounds=prefecture?await pool.query(`select
    percentile_cont(0.01) within group(order by lng) as west,
    percentile_cont(0.01) within group(order by lat) as south,
    percentile_cont(0.99) within group(order by lng) as east,
    percentile_cont(0.99) within group(order by lat) as north
    from stores where current_presence='PRESENT'${condition}`,values):null;
  const brands=Object.fromEntries(['FAMILY_MART','LAWSON','SEVEN_ELEVEN'].map(family=>[family,stores.rows.find(row=>row.brand_family===family)?.count??0]));
  const lawsonVariants=emptyLawsonVariantCounts();
  for(const row of lawsonNames.rows)addLawsonVariantCount(lawsonVariants,String(row.canonical_name),Number(row.count));
  return {ok:true,mode:'database',db:'connected',...result.rows[0],store_count:stores.rows.reduce((sum,row)=>sum+row.count,0),brands,lawson_variants:lawsonVariants,lawson_official_count:lawsonOfficialBenchmark.count,lawson_official_as_of:lawsonOfficialBenchmark.as_of,lawson_official_source:lawsonOfficialBenchmark.source,scope_prefecture:prefecture,extent:bounds?.rows[0]?.west==null?null:bounds.rows[0]};
}
