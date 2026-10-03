import type { Filters } from './types';

export function parseFilters(params:URLSearchParams):Filters {
  const status=params.get('status')??'CLOSED_CONFIRMED';
  const brand=params.get('brand')??'ALL';
  const rawDistance=Number(params.get('distance')??100);
  const rawPage=Number(params.get('page')??0);
  const rawBBox=params.get('bbox')?.split(',').map(Number);
  const bbox=rawBBox?.length===4 && rawBBox.every(Number.isFinite) && rawBBox[0]<rawBBox[2] && rawBBox[1]<rawBBox[3] ? rawBBox:undefined;
  return {status:['CLOSED_CONFIRMED','CLOSED_SUSPECTED','CLOSED_BOTH','MISSING','ALL'].includes(status)?status:'CLOSED_CONFIRMED',brand:['ALL','FAMILY_MART','LAWSON'].includes(brand)?brand:'ALL',distance:[50,100,300].includes(rawDistance)?rawDistance:100,municipality:params.get('municipality')??'',from:params.get('from')??'',to:params.get('to')??'',bbox,page:Number.isInteger(rawPage)&&rawPage>=0?Math.min(rawPage,1000):0};
}
