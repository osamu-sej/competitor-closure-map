import { prefectures } from './prefectures';

export const storeBrands = ['FAMILY_MART', 'LAWSON', 'SEVEN_ELEVEN'];
export type StoreFilters = { brands:string[]; prefecture:string; municipality:string; q:string; page:number };

export function parseStoreFilters(params:URLSearchParams):StoreFilters {
  const requested=params.get('brands');
  const brands=requested===null ? storeBrands : [...new Set(requested.split(',').filter(value=>storeBrands.includes(value)))];
  const prefecture=params.get('prefecture')??'';
  const rawPage=Number(params.get('page')??0);
  return {
    brands,
    prefecture:prefectures.some(value=>value===prefecture)?prefecture:'',
    municipality:(params.get('municipality')??'').trim().slice(0,80),
    q:(params.get('q')??'').trim().slice(0,80),
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
