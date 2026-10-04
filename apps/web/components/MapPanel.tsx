'use client';
import { useEffect, useRef, useState } from 'react';
import type { Map as MapType, Marker } from 'maplibre-gl';
import type { Closure } from '../lib/types';

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
      instance=new Map({container:container.current,style:process.env.NEXT_PUBLIC_MAP_STYLE_URL||'https://tiles.openfreemap.org/styles/liberty',center:[139.41,35.51],zoom:10.5});
      map.current=instance;
      instance.addControl(new NavigationControl({showCompass:false}),'bottom-left');
      instance.on('load',()=>setReady(true));
      instance.on('error',(event)=>{if(!ready && String(event.error).includes('style')) setError('地図スタイルを取得できません。設定とネットワークを確認してください。');});
    }).catch(()=>setError('地図を読み込めません。'));
    return ()=>{disposed=true;markers.current.forEach(marker=>marker.remove());instance?.remove();map.current=null;};
  },[]);
  useEffect(()=>{
    if(!ready||!map.current) return;
    let active=true;
    import('maplibre-gl').then(({Marker})=>{
      if(!active||!map.current)return;
      markers.current.forEach(marker=>marker.remove());
      markers.current=items.map(item=>{
        const element=document.createElement('button');
        element.className=`store-marker ${item.status==='CLOSED_CONFIRMED'?'confirmed':'suspected'} ${selected?.id===item.id?'active':''}`;
        element.type='button';element.title=item.store.canonical_name;element.setAttribute('aria-label',item.store.canonical_name);
        element.textContent='×';element.onclick=()=>onSelect(item.id);
        return new Marker({element,anchor:'center'}).setLngLat([item.store.lng,item.store.lat]).addTo(map.current!);
      });
    });
    return ()=>{active=false;};
  },[items,selected?.id,ready,onSelect]);
  useEffect(()=>{
    const m=map.current;if(!ready||!m)return;
    for(const layer of ['selection-line','selection-circle']) if(m.getLayer(layer)) m.removeLayer(layer);
    for(const source of ['selection-line','selection-circle']) if(m.getSource(source)) m.removeSource(source);
    if(!selected)return;
    const [lng,lat]=[selected.store.lng,selected.store.lat];
    m.flyTo({center:[lng,lat],zoom:16.7,essential:true});
    const circle=[] as [number,number][];
    for(let i=0;i<=64;i++){const angle=i*2*Math.PI/64;circle.push([lng+distance*Math.cos(angle)/(111320*Math.cos(lat*Math.PI/180)),lat+distance*Math.sin(angle)/111320]);}
    m.addSource('selection-circle',{type:'geojson',data:{type:'Feature',geometry:{type:'Polygon',coordinates:[circle]},properties:{}}});
    m.addLayer({id:'selection-circle',type:'fill',source:'selection-circle',paint:{'fill-color':'#e26038','fill-opacity':0.12}});
    if(selected.nearest_seven){
      m.addSource('selection-line',{type:'geojson',data:{type:'Feature',geometry:{type:'LineString',coordinates:[[lng,lat],[selected.nearest_seven.lng,selected.nearest_seven.lat]]},properties:{}}});
      m.addLayer({id:'selection-line',type:'line',source:'selection-line',paint:{'line-color':'#152b49','line-width':3,'line-dasharray':[2,2]}});
    }
  },[selected,ready,distance]);
  const seven=selected?.nearest_seven;
  useEffect(()=>{
    if(!ready||!map.current||!seven)return;
    let marker:Marker|undefined;let active=true;
    import('maplibre-gl').then(({Marker})=>{if(!active||!map.current)return;const el=document.createElement('div');el.className='seven-marker';el.textContent='7';el.title=seven.canonical_name;marker=new Marker({element:el,anchor:'center'}).setLngLat([seven.lng,seven.lat]).addTo(map.current);});
    return ()=>{active=false;marker?.remove();};
  },[ready,seven?.id]);
  return <section className="map-panel" aria-label="競合閉店地図"><div ref={container} className="map-canvas" data-testid="map"/>{!ready&&!error&&<div className="map-message">地図を読み込み中…</div>}{error&&<div className="map-message error">{error}</div>}{selected?.nearest_seven&&<div className="map-distance"><b>{Math.round(selected.distance_m??0)}m</b><span>{selected.store.canonical_name} → {selected.nearest_seven.canonical_name}</span><span>選択範囲: {distance===1000?'1km':`${distance}m`} の円</span></div>}<div className="map-attribution">地図 © OpenFreeMap / OpenStreetMap contributors · POI: OpenPOI（出典は各観測記録）</div></section>;
}
