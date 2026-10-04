'use client';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Store } from '../lib/types';
import { prefectures } from '../lib/prefectures';
import StoreMapPanel from './StoreMapPanel';

const allBrands=['FAMILY_MART','LAWSON','SEVEN_ELEVEN'];
const brandLabels:Record<string,string>={FAMILY_MART:'ファミリーマート',LAWSON:'ローソン',SEVEN_ELEVEN:'セブン-イレブン'};

export default function StoreExplorer({prefecture,setPrefecture}:{prefecture:string;setPrefecture:(value:string)=>void}) {
  const [brands,setBrands]=useState(allBrands);
  const [municipality,setMunicipality]=useState('');
  const [query,setQuery]=useState('');
  const [appliedQuery,setAppliedQuery]=useState('');
  const [page,setPage]=useState(0);
  const [items,setItems]=useState<Store[]>([]);
  const [total,setTotal]=useState(0);
  const [selected,setSelected]=useState<Store|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  useEffect(()=>{const timer=setTimeout(()=>{setAppliedQuery(query.trim());setPage(0);},250);return()=>clearTimeout(timer);},[query]);
  const params=useMemo(()=>new URLSearchParams({brands:brands.join(','),prefecture,municipality,q:appliedQuery,page:String(page)}),[brands,prefecture,municipality,appliedQuery,page]);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('');
    fetch(`/api/stores?${params}`,{signal:controller.signal})
      .then(async response=>{if(!response.ok)throw new Error('店舗一覧を取得できません。');return response.json();})
      .then(data=>{setItems(data.items);setTotal(data.total);})
      .catch(err=>{if(err.name!=='AbortError')setError(err.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[params]);
  const select=useCallback((id:string)=>{
    const found=items.find(item=>item.id===id);
    if(found){setSelected(found);return;}
    fetch(`/api/stores/${id}`).then(response=>response.ok?response.json():null).then(setSelected).catch(()=>{});
  },[items]);
  const toggleBrand=(brand:string)=>{setBrands(current=>current.includes(brand)?current.filter(value=>value!==brand):[...current,brand]);setPage(0);setSelected(null);};
  return <>
    <div className="filterbar store-filterbar">
      <div className="brand-filter" role="group" aria-label="店舗ブランド"><span className="filter-label">店舗ブランド</span><div className="brand-options">{allBrands.map(brand=><label key={brand}><input type="checkbox" checked={brands.includes(brand)} onChange={()=>toggleBrand(brand)}/>{brandLabels[brand]}</label>)}</div></div>
      <label>都道府県<select aria-label="都道府県" value={prefecture} onChange={event=>{setPrefecture(event.target.value);setPage(0);setSelected(null);}}><option value="">全国</option>{prefectures.map(name=><option key={name} value={name}>{name}</option>)}</select></label>
      <label>市区町村<input aria-label="市区町村" placeholder="すべて" value={municipality} onChange={event=>{setMunicipality(event.target.value);setPage(0);setSelected(null);}}/></label>
      <label>店名・住所<input aria-label="店名・住所" placeholder="店舗を検索" value={query} onChange={event=>setQuery(event.target.value)}/></label>
    </div>
    <div className="content store-content">
      <StoreMapPanel brands={brands} prefecture={prefecture} municipality={municipality} q={appliedQuery} selected={selected} onSelect={select}/>
      <aside className="sidebar"><div className="sidebar-heading"><div><span className="eyebrow">OBSERVED STORES</span><h2>収録店舗一覧 <small>{total.toLocaleString()} 件</small></h2></div><div className="legend">収録できた実店舗の位置</div></div>
        {loading&&<div className="state-message">読み込み中…</div>}
        {error&&<div className="state-message error">{error}</div>}
        {!loading&&!error&&!items.length&&<div className="state-message"><strong>該当する収録店舗はありません</strong><p>ブランド・地域・検索語を変更してください。</p></div>}
        <div className="result-list">{items.map(store=><button type="button" key={store.id} className={`result-card store-result ${selected?.id===store.id?'selected':''}`} onClick={()=>select(store.id)}><div className="card-top"><span className={`brand-badge ${store.brand_family==='FAMILY_MART'?'family':''}`}>{brandLabels[store.brand_family]}</span><span className="status-badge">OpenPOI収録</span></div><h3>{store.canonical_name}</h3><p className="card-city">{store.prefecture} {store.city}</p><p className="store-address">{store.address}</p></button>)}</div>
        {total>100&&<div className="pagination"><button disabled={page===0} onClick={()=>setPage(page-1)}>前へ</button><span>{page+1} / {Math.ceil(total/100)}</span><button disabled={(page+1)*100>=total} onClick={()=>setPage(page+1)}>次へ</button></div>}
      </aside>
    </div>
    {selected&&<div className="detail-backdrop" onClick={()=>setSelected(null)}><section className="detail-panel" role="dialog" aria-label="収録店舗詳細" onClick={event=>event.stopPropagation()}><button className="close" aria-label="詳細を閉じる" onClick={()=>setSelected(null)}>×</button><span className="eyebrow">OBSERVED STORE</span><h2>{selected.canonical_name}</h2><div className="detail-tags"><span className="brand-badge">{brandLabels[selected.brand_family]}</span><span>OpenPOI収録</span></div><div className="detail-scroll"><h3>収録情報</h3><dl><dt>住所</dt><dd>{selected.address}</dd><dt>都道府県</dt><dd>{selected.prefecture}</dd><dt>市区町村</dt><dd>{selected.city}</dd><dt>位置</dt><dd>{selected.lat.toFixed(6)}, {selected.lng.toFixed(6)}</dd></dl><p className="store-caveat">OpenPOIの掲載地点です。営業中かどうか、全店舗が収録されているかは保証されません。</p></div></section></div>}
  </>;
}
