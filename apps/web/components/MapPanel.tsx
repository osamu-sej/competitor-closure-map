'use client';
import { useEffect, useRef, useState } from 'react';
import type { Map as MapType, Marker } from 'maplibre-gl';
import type { Closure, Store } from '../lib/types';

const logoPaths:Record<string,string>={
  FAMILY_MART:'/brand-logos/familymart.svg',
  LAWSON:'/brand-logos/lawson.svg',
  SEVEN_ELEVEN:'/brand-logos/seven-eleven.svg'
};

function fitStores(map:MapType, stores:Store[], paddingMeters:number) {
  if (!stores.length) return;
  const lats=stores.map(store=>store.lat);
  const lngs=stores.map(store=>store.lng);
  const centerLat=(Math.min(...lats)+Math.max(...lats))/2;
  const latPadding=paddingMeters/111320;
  const lngPadding=paddingMeters/(111320*Math.cos(centerLat*Math.PI/180));
  map.fitBounds([
    [Math.min(...lngs)-lngPadding,Math.min(...lats)-latPadding],
    [Math.max(...lngs)+lngPadding,Math.max(...lats)+latPadding]
  ],{padding:70,maxZoom:18.5,duration:450,essential:true});
}

function logoMarker(store:Store, kind:'closure'|'seven', active=false):HTMLButtonElement {
  const element=document.createElement('button');
  element.type='button';
  element.className='map-store-marker '+kind+(active?' active':'');
  element.title=store.canonical_name;
  element.setAttribute('aria-label',(kind==='seven'?'近隣セブン-イレブン':'閉店・消失店舗')+': '+store.canonical_name);
  const image=document.createElement('img');
  image.src=logoPaths[store.brand_family];
  image.alt='';
  image.draggable=false;
  element.appendChild(image);
  if (kind==='closure') {
    const badge=document.createElement('span');
    badge.className='closure-mark';
    badge.textContent='×';
    badge.setAttribute('aria-hidden','true');
    element.appendChild(badge);
  }
  return element;
}

export default function MapPanel({items,selected,distance,onSelect}:{items:Closure[];selected:Closure|null;distance:number;onSelect:(id:string)=>void}) {
  const container=useRef<HTMLDivElement>(null);
  const map=useRef<MapType|null>(null);
  const markers=useRef<Marker[]>([]);
  const [ready,setReady]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    let disposed=false;
    let instance:MapType|null=null;
    import('maplibre-gl').then(({Map,NavigationControl,setWorkerUrl})=>{
      if(disposed||!container.current) return;
      setWorkerUrl('/maplibre-gl-worker.mjs');
      instance=new Map({container:container.current,style:process.env.NEXT_PUBLIC_MAP_STYLE_URL||'https://tiles.openfreemap.org/styles/liberty',center:[137.5,37.0],zoom:4.5});
      map.current=instance;
      instance.addControl(new NavigationControl({showCompass:false}),'bottom-left');
      instance.on('load',()=>setReady(true));
      instance.on('error',(event)=>{if(String(event.error).includes('style')) setError('地図スタイルを取得できません。設定とネットワークを確認してください。');});
    }).catch(()=>setError('地図を読み込めません。'));
    return ()=>{disposed=true;markers.current.forEach(marker=>marker.remove());instance?.remove();map.current=null;};
  },[]);
  useEffect(()=>{
    if(!ready||!map.current)return;
    let active=true;
    import('maplibre-gl').then(({Marker})=>{
      if(!active||!map.current)return;
      markers.current.forEach(marker=>marker.remove());
      const sevenStores=[...new Map(items.filter(item=>item.nearest_seven).map(item=>[item.nearest_seven!.id,item.nearest_seven!])).values()];
      const sevenMarkers=sevenStores.map(store=>{
        const element=logoMarker(store,'seven',selected?.nearest_seven?.id===store.id);
        element.onclick=()=>{
          const related=items.find(item=>item.nearest_seven?.id===store.id);
          if(related)onSelect(related.id);
        };
        return new Marker({element,anchor:'center'}).setLngLat([store.lng,store.lat]).addTo(map.current!);
      });
      const closureMarkers=items.map(item=>{
        const element=logoMarker(item.store,'closure',selected?.id===item.id);
        element.onclick=()=>onSelect(item.id);
        return new Marker({element,anchor:'center'}).setLngLat([item.store.lng,item.store.lat]).addTo(map.current!);
      });
      markers.current=[...sevenMarkers,...closureMarkers];
    });
    return()=>{active=false;};
  },[items,selected?.id,selected?.nearest_seven?.id,ready,onSelect]);
  useEffect(()=>{
    const m=map.current;if(!ready||!m)return;
    for(const layer of ['selection-line','selection-circle'])if(m.getLayer(layer))m.removeLayer(layer);
    for(const source of ['selection-line','selection-circle'])if(m.getSource(source))m.removeSource(source);
    if(!selected){
      const stores=items.flatMap(item=>item.nearest_seven?[item.store,item.nearest_seven]:[item.store]);
      fitStores(m,stores,100);
      return;
    }
    const [lng,lat]=[selected.store.lng,selected.store.lat];
    const circle=[] as [number,number][];
    for(let i=0;i<=64;i++){const angle=i*2*Math.PI/64;circle.push([lng+distance*Math.cos(angle)/(111320*Math.cos(lat*Math.PI/180)),lat+distance*Math.sin(angle)/111320]);}
    m.addSource('selection-circle',{type:'geojson',data:{type:'Feature',geometry:{type:'Polygon',coordinates:[circle]},properties:{}}});
    m.addLayer({id:'selection-circle',type:'fill',source:'selection-circle',paint:{'fill-color':'#e26038','fill-opacity':0.12}});
    if(selected.nearest_seven){
      m.addSource('selection-line',{type:'geojson',data:{type:'Feature',geometry:{type:'LineString',coordinates:[[lng,lat],[selected.nearest_seven.lng,selected.nearest_seven.lat]]},properties:{}}});
      m.addLayer({id:'selection-line',type:'line',source:'selection-line',paint:{'line-color':'#152b49','line-width':3,'line-dasharray':[2,2]}});
    }
    fitStores(m,selected.nearest_seven?[selected.store,selected.nearest_seven]:[selected.store],100);
  },[items,selected,ready,distance]);
  return <section className={'map-panel'+(selected?' has-selection':'')} aria-label="競合閉店地図">
    <div ref={container} className="map-canvas" data-testid="map"/>
    {!ready&&!error&&<div className="map-message">地図を読み込み中…</div>}{error&&<div className="map-message error">{error}</div>}
    {selected?.nearest_seven&&<div className="map-distance"><b>{Math.round(selected.distance_m??0)}m</b><span>{selected.store.canonical_name} → {selected.nearest_seven.canonical_name}</span><span>選択範囲: {distance===1000?'1km':distance+'m'} の円</span></div>}
    <div className="map-legend" aria-label="地図の凡例"><span><img src={logoPaths.SEVEN_ELEVEN} alt=""/> 近隣セブン-イレブン</span><span><img src={logoPaths.FAMILY_MART} alt=""/><img src={logoPaths.LAWSON} alt=""/> 閉店・消失店舗 <b>×</b></span></div>
    <div className="map-attribution">地図 © OpenFreeMap / OpenStreetMap contributors · POI: OpenPOI（出典は各観測記録）</div>
  </section>;
}
