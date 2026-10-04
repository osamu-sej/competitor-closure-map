'use client';
import { useEffect, useRef, useState } from 'react';
import type { Map as MapType, Marker } from 'maplibre-gl';
import type { Store, StoreMapPoint } from '../lib/types';

const logos:Record<string,string>={FAMILY_MART:'/brand-logos/familymart.svg',LAWSON:'/brand-logos/lawson.svg',SEVEN_ELEVEN:'/brand-logos/seven-eleven.svg'};

type Extent={west:number;south:number;east:number;north:number};
export default function StoreMapPanel({brands,prefecture,municipality,q,extent,selected,onSelect}:{brands:string[];prefecture:string;municipality:string;q:string;extent:Extent|null;selected:Store|null;onSelect:(id:string)=>void}) {
  const container=useRef<HTMLDivElement>(null);
  const map=useRef<MapType|null>(null);
  const markers=useRef<Marker[]>([]);
  const [ready,setReady]=useState(false);
  const [points,setPoints]=useState<StoreMapPoint[]>([]);
  const [truncated,setTruncated]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    let disposed=false;
    let instance:MapType|null=null;
    import('maplibre-gl').then(({Map,NavigationControl,setWorkerUrl})=>{
      if(disposed||!container.current)return;
      setWorkerUrl('/maplibre-gl-worker.mjs');
      instance=new Map({container:container.current,style:process.env.NEXT_PUBLIC_MAP_STYLE_URL||'https://tiles.openfreemap.org/styles/liberty',center:[137.5,37],zoom:4.5});
      map.current=instance;
      instance.addControl(new NavigationControl({showCompass:false}),'bottom-left');
      instance.on('load',()=>{instance?.fitBounds([[122,20],[154.5,46.1]],{padding:20,duration:0});setReady(true);});
      instance.on('error',event=>{if(String(event.error).includes('style'))setError('地図スタイルを取得できません。');});
    }).catch(()=>setError('地図を読み込めません。'));
    return()=>{disposed=true;markers.current.forEach(marker=>marker.remove());instance?.remove();map.current=null;};
  },[]);
  useEffect(()=>{
    const instance=map.current;
    if(!ready||!instance)return;
    if(!prefecture){instance.fitBounds([[122,20],[154.5,46.1]],{padding:20,duration:350});return;}
    if(extent){
      const west=extent.west===extent.east?extent.west-0.02:extent.west;
      const east=extent.west===extent.east?extent.east+0.02:extent.east;
      const south=extent.south===extent.north?extent.south-0.02:extent.south;
      const north=extent.south===extent.north?extent.north+0.02:extent.north;
      instance.fitBounds([[west,south],[east,north]],{padding:65,maxZoom:12,duration:350});
    }
  },[ready,prefecture,extent?.west,extent?.south,extent?.east,extent?.north]);
  useEffect(()=>{
    const instance=map.current;
    if(!ready||!instance)return;
    let controller:AbortController|null=null;
    const load=()=>{
      controller?.abort();controller=new AbortController();
      const bounds=instance.getBounds();
      const bbox=[bounds.getWest(),bounds.getSouth(),bounds.getEast(),bounds.getNorth()]
        .map((value,index)=>index%2===0?Math.max(-180,Math.min(180,value)):Math.max(-90,Math.min(90,value)));
      const params=new URLSearchParams({bbox:bbox.join(','),zoom:String(instance.getZoom()),brands:brands.join(','),prefecture,municipality,q});
      fetch(`/api/stores/map?${params}`,{signal:controller.signal})
        .then(async response=>{if(!response.ok)throw new Error('地図の店舗を取得できません。');return response.json();})
        .then(data=>{setPoints(data.points);setTruncated(data.truncated);setError('');})
        .catch(err=>{if(err.name!=='AbortError')setError(err.message);});
    };
    instance.on('moveend',load);load();
    return()=>{controller?.abort();instance.off('moveend',load);};
  },[ready,brands,prefecture,municipality,q]);
  useEffect(()=>{
    const instance=map.current;
    if(!ready||!instance)return;
    let active=true;
    import('maplibre-gl').then(({Marker})=>{
      if(!active||!map.current)return;
      markers.current.forEach(marker=>marker.remove());
      markers.current=points.map(point=>{
        const element=document.createElement('button');element.type='button';
        element.className=`map-current-marker ${point.count>1?'cluster':''} ${selected?.id===point.id?'active':''}`;
        element.title=point.count>1?`${point.count}件・拡大して表示`:point.canonical_name??'収録店舗';
        element.setAttribute('aria-label',element.title);
        for(const brand of point.brand_family==='MIXED'?brands:[point.brand_family]){
          const image=document.createElement('img');image.src=logos[brand];image.alt='';element.appendChild(image);
        }
        if(point.count>1){const count=document.createElement('b');count.textContent=String(point.count);element.appendChild(count);}
        element.onclick=()=>{
          if(point.id)onSelect(point.id);
          else map.current?.easeTo({center:[point.lng,point.lat],zoom:Math.min(map.current.getZoom()+3,19),duration:350});
        };
        return new Marker({element,anchor:'center'}).setLngLat([point.lng,point.lat]).addTo(map.current!);
      });
    });
    return()=>{active=false;};
  },[points,selected?.id,ready,onSelect]);
  useEffect(()=>{
    if(selected&&ready)map.current?.flyTo({center:[selected.lng,selected.lat],zoom:Math.max(map.current.getZoom(),16),duration:450,essential:true});
  },[selected?.id,ready]);
  return <section className="map-panel store-map-panel" aria-label="全国の収録店舗地図">
    <div ref={container} className="map-canvas" data-testid="store-map"/>
    {!ready&&!error&&<div className="map-message">地図を読み込み中…</div>}
    {error&&<div className="map-message error">{error}</div>}
    <div className="store-map-hint">丸数字は収録店舗数です。拡大すると店舗ごとのロゴになります。{truncated&&'表示数の上限に達しました。地図を拡大してください。'}</div>
    <div className="map-attribution">地図 © OpenFreeMap / OpenStreetMap contributors · POI: OpenPOI（部分収録）</div>
  </section>;
}
