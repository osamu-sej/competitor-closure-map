import { prefectures } from './prefectures';

export const storeBrands = ['FAMILY_MART', 'LAWSON', 'SEVEN_ELEVEN'];
export type StoreFilters = { brands:string[]; prefecture:string; municipality:string; q:string; from:string; to:string; page:number };
export class StoreFilterError extends Error {}

function dateParam(value:string):string {
  if(value && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`)) || new Date(`${value}T00:00:00Z`).toISOString().slice(0,10)!==value))
    throw new StoreFilterError('日付はYYYY-MM-DD形式で指定してください。');
  return value;
}

export function parseStoreFilters(params:URLSearchParams):StoreFilters {
  const requested=params.get('brands');
  const brands=requested===null ? storeBrands : [...new Set(requested.split(',').filter(value=>storeBrands.includes(value)))];
  const prefecture=params.get('prefecture')??'';
  const rawPage=Number(params.get('page')??0);
  const from=dateParam(params.get('from')??'');
  const to=dateParam(params.get('to')??'');
  if(from&&to&&from>to)throw new StoreFilterError('期間の開始日は終了日以前にしてください。');
  return {
    brands,
    prefecture:prefectures.some(value=>value===prefecture)?prefecture:'',
    municipality:(params.get('municipality')??'').trim().slice(0,80),
    q:(params.get('q')??'').trim().slice(0,80),
    from,to,
    page:Number.isInteger(rawPage)&&rawPage>=0?Math.min(rawPage,1000):0
  };
}

export function parseMapViewport(params:URLSearchParams):{bbox:[number,number,number,number];zoom:number}|null {
  const values=params.get('bbox')?.split(',').map(Number);
  const zoom=Number(params.get('zoom'));
  if (!values||values.length!==4||!values.every(Number.isFinite)||!Number.isFinite(zoom)||zoom<0||zoom>22) return null;
  const [west,south,east,north]=values;
  if(west < -180||east > 180||south < -90||north > 90||west>=east||south>=north) return null;
  return {bbox:[west,south,east,north],zoom};
}
