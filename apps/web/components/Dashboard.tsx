'use client';
import { useCallback, useEffect, useMemo, useState } from 'react';
import MapPanel from './MapPanel';
import StoreExplorer from './StoreExplorer';
import type { Closure } from '../lib/types';
import { prefectures } from '../lib/prefectures';
import packageInfo from '../../../package.json';
import { googleMapsSearchUrl } from '../lib/maps-url';
import { lawsonVariantFromName, lawsonVariantLabels } from '../lib/lawson-variant';

const labels:Record<string,string>={CLOSED_CONFIRMED:'閉店確認済み',CLOSED_SUSPECTED:'閉店の可能性',MISSING:'消失候補',REOPENED:'再出現'};
const statusDescriptions:Record<string,string>={
  CLOSED_CONFIRMED:'公式発表や現地確認などの根拠で閉店を確認した店舗。店舗データから消えただけでは含めません。',
  CLOSED_BOTH:'「閉店確認済み」と「閉店の可能性」を合わせて表示します。消失候補だけの店舗は含めません。',
  CLOSED_SUSPECTED:'連続して店舗データに見つからないなど、閉店の可能性はありますが、確認できる根拠が不足しています。',
  MISSING:'前回は店舗データに存在し、最新の取得では見つからない店舗。移転・一時休業・データ欠落の可能性もあり、閉店とは判定しません。'
};
const benchmarkBrands=[
  {family:'FAMILY_MART',label:'ファミリーマート'},
  {family:'LAWSON',label:'ローソン系'},
  {family:'SEVEN_ELEVEN',label:'セブン-イレブン'},
] as const;
const liveDataMode=process.env.NEXT_PUBLIC_DATA_MODE==='database'||process.env.NEXT_PUBLIC_DATA_MODE==='sheets';
const date=(value?:string|null)=>value?new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value)):'未確認';
const day=(value?:string|null)=>value?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value)):'';
export default function Dashboard(){
  const [storeMode,setStoreMode]=useState(liveDataMode);
  const [status,setStatus]=useState('CLOSED_CONFIRMED');const [selectedBrands,setSelectedBrands]=useState(['FAMILY_MART','LAWSON']);const [distance,setDistance]=useState(100);
  const [prefecture,setPrefecture]=useState('');const [municipality,setMunicipality]=useState('');const [from,setFrom]=useState('');const [to,setTo]=useState('');
  const [health,setHealth]=useState<{first_snapshot:string|null;latest_snapshot:string|null;snapshot_day_count:number;snapshot_count:number;prefecture_count:number;store_count:number;brands:Record<string,number>;official_brand_counts?:Record<string,number>;official_brand_as_of?:string;official_brand_sources?:Record<string,string>;lawson_variants?:Record<string,number>;lawson_official_count?:number;lawson_official_as_of?:string;lawson_official_source?:string;scope_prefecture:string;extent:{west:number;south:number;east:number;north:number}|null}|null>(null);
  const [items,setItems]=useState<Closure[]>([]);const [total,setTotal]=useState(0);const [page,setPage]=useState(0);
  const [selectedId,setSelectedId]=useState<string|null>(null);const [detail,setDetail]=useState<Closure|null>(null);
  const [loading,setLoading]=useState(true);const [error,setError]=useState('');
  const params=useMemo(()=>new URLSearchParams({status,brands:selectedBrands.join(','),distance:String(distance),prefecture,municipality,from,to,page:String(page)}),[status,selectedBrands,distance,prefecture,municipality,from,to,page]);
  useEffect(()=>{const controller=new AbortController();fetch(`/api/health?prefecture=${encodeURIComponent(prefecture)}`,{signal:controller.signal}).then(response=>response.json()).then(setHealth).catch(()=>{});return()=>controller.abort();},[prefecture]);
  useEffect(()=>{const controller=new AbortController();setLoading(true);setError('');fetch(`/api/closures?${params}`,{signal:controller.signal}).then(async response=>{if(!response.ok)throw new Error((await response.json()).error);return response.json();}).then(data=>{setItems(data.items);setTotal(data.total);setSelectedId(current=>data.items.some((item:Closure)=>item.id===current)?current:null);}).catch(err=>{if(err.name!=='AbortError')setError(err.message||'データ取得に失敗しました。');}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});return()=>controller.abort();},[params]);
  useEffect(()=>{if(!selectedId){setDetail(null);return;}const controller=new AbortController();fetch(`/api/closures/${selectedId}`,{signal:controller.signal}).then(r=>r.json()).then(setDetail).catch(()=>{});return()=>controller.abort();},[selectedId]);
  const selected=items.find(item=>item.id===selectedId)??null;
  const lawsonBreakdown=health?.lawson_variants?Object.entries(lawsonVariantLabels).map(([key,label])=>`${label} ${(health.lawson_variants?.[key]??0).toLocaleString()}`).join('・'):'';
  const nationalBenchmarks=benchmarkBrands.map(({family,label})=>{
    const candidate=health?.brands[family]??0;
    const official=health?.official_brand_counts?.[family]??0;
    const delta=candidate-official;
    return {family,label,candidate,official,delta,deltaPercent:official?Math.abs(delta)/official*100:0,source:health?.official_brand_sources?.[family]??''};
  });
  const select=useCallback((id:string)=>setSelectedId(id),[]);
  const toggleBrand=(family:string)=>{setSelectedBrands(current=>current.includes(family)?current.filter(value=>value!==family):[...current,family]);setPage(0);};
  const change=(fn:(value:string)=>void)=>(event:React.ChangeEvent<HTMLSelectElement|HTMLInputElement>)=>{fn(event.target.value);setPage(0);};
  const demoMode=!liveDataMode;
  const firstDay=health?.scope_prefecture===prefecture?day(health.first_snapshot):'';
  const beforeCollection=Boolean(firstDay&&from&&from<firstDay);
  const entirelyBeforeCollection=Boolean(firstDay&&to&&to<firstDay);
  return <main className={'dashboard'+(demoMode?' demo-mode':' data-mode')}>
    <header className="topbar"><div className="brandmark"><div className="brand-icon">↗</div><div><h1>競合閉店MAP <a className="version-link" href="/api/version" title="バージョンとデプロイコミット">v{packageInfo.version}</a></h1><p>全国 / 店舗マスタ差分モニター</p></div></div><div className="top-note"><span className="live-dot"/> {demoMode?'実データ未接続':'実データ'} <span className="top-divider"/> 全国47都道府県</div></header>
    {demoMode&&<div className="demo-banner" role="status"><strong>実データは未収集です</strong><span>表示される店舗は架空の動作確認用データです。期間を指定しても、過去の実店舗の閉店状況は検索できません。</span></div>}
    {!demoMode&&<div className="demo-banner data-banner" role="status"><strong>3社の公式店舗数との比較</strong><span>
      {health?.scope_prefecture===prefecture&&health.latest_snapshot?<>
        <div>最終取得 {date(health.latest_snapshot)} / {prefecture||'全国'} {health.store_count.toLocaleString()}件。基準日は {health.official_brand_as_of??'未確認'} です。</div>
        <div className="brand-benchmarks">{nationalBenchmarks.map(row=><div key={row.family}><b>{row.label}</b>　{prefecture?<>県内候補 {row.candidate.toLocaleString()}件（全国公式 {row.official.toLocaleString()}店）</>:<>候補 {row.candidate.toLocaleString()}件 / 公式 {row.official.toLocaleString()}店 / 差 {row.delta>0?'+':''}{row.delta.toLocaleString()}件（{row.deltaPercent.toFixed(1)}%）</>}　<a href={row.source||'#'} target="_blank" rel="noreferrer">公式 ↗</a></div>)}</div>
        {prefecture&&<div>県別候補と全国公式値は集計範囲が異なるため、差分比較は全国表示で確認してください。</div>}
      </>: '収録件数を読み込み中です。'}
      <div>候補はカテゴリが <code>convenience_store</code> で、代表ソースまたは統合出典にOvertureを含むPOIです。JFF由来だけの営業許可・届出候補は除いています。公式店舗名簿との1店ずつの照合や、営業中であることを保証した数字ではありません。</div>
      <div>ローソン店名内訳：{lawsonBreakdown||'分類中'}（ローソングループ公式値にはナチュラルローソン・ローソンストア100等を含む）。最寄りセブンは収録候補内の暫定値です。</div>
      <a href="https://github.com/osamu-sej/competitor-closure-map/blob/main/docs/brand-count-audit-2026-10-07.md" target="_blank" rel="noreferrer">3社の件数調査・判定条件 ↗</a>
    </span></div>}
    <div className="view-switch" role="group" aria-label="表示切替"><button type="button" className={storeMode?'active':''} onClick={()=>setStoreMode(true)}>収録店舗マップ</button><button type="button" className={!storeMode?'active':''} onClick={()=>setStoreMode(false)}>閉店・消失シグナル</button></div>
    {storeMode?<StoreExplorer prefecture={prefecture} setPrefecture={setPrefecture} extent={health?.scope_prefecture===prefecture?health.extent:null}/>:<>
    <div className="filterbar">
      <div className="brand-filter" role="group" aria-label="ブランド"><span className="filter-label">ブランド</span><div className="brand-options"><label><input type="checkbox" checked={selectedBrands.includes('FAMILY_MART')} onChange={()=>toggleBrand('FAMILY_MART')}/> FamilyMart</label><label><input type="checkbox" checked={selectedBrands.includes('LAWSON')} onChange={()=>toggleBrand('LAWSON')}/> LAWSON</label></div></div>
      <label>状態<select aria-label="状態" value={status} onChange={change(setStatus)}><option value="CLOSED_CONFIRMED">閉店確認済み</option><option value="CLOSED_BOTH">確認済み＋可能性あり</option><option value="CLOSED_SUSPECTED">閉店の可能性</option><option value="MISSING">消失候補</option></select></label>
      <details className="status-guide"><summary>状態の説明</summary><div className="status-guide-panel"><strong>状態の意味</strong>{(['CLOSED_CONFIRMED','CLOSED_BOTH','CLOSED_SUSPECTED','MISSING'] as const).map(key=><div key={key}><b>{key==='CLOSED_BOTH'?'確認済み＋可能性あり':labels[key]}</b><p>{statusDescriptions[key]}</p></div>)}<small>移転・一時休業・名称変更・データ不備・再出現は閉店一覧の対象外です。</small></div></details>
      <label>距離<select aria-label="距離" value={distance} onChange={event=>{setDistance(Number(event.target.value));setPage(0);}}><option value={50}>50m 以内</option><option value={100}>100m 以内</option><option value={300}>300m 以内</option><option value={500}>500m 以内</option><option value={1000}>1km 以内</option></select></label>
      <label>都道府県<select aria-label="都道府県" value={prefecture} onChange={change(setPrefecture)}><option value="">全国</option>{prefectures.map(name=><option key={name} value={name}>{name}</option>)}</select></label>
      <label>市区町村<input aria-label="市区町村" placeholder="すべて" value={municipality} onChange={change(setMunicipality)}/></label>
      <label>期間 開始<input aria-label="期間 開始" type="date" value={from} onChange={change(setFrom)}/></label><label>終了<input aria-label="期間 終了" type="date" value={to} onChange={change(setTo)}/></label>
    </div>
    {!demoMode&&<div className="closure-coverage-note" role="status"><strong>閉店検索の対象期間</strong> {firstDay?`観測開始 ${date(health?.first_snapshot)}・観測日 ${health?.snapshot_day_count??0}日分。`:'観測期間を確認中です。'}{beforeCollection||entirelyBeforeCollection?'指定期間には観測開始前の日付が含まれます。開始前の閉店は未収集で、0件は閉店がなかったことを意味しません。':'期間指定は収集済みの閉店・消失イベントを絞り込みます。観測開始前の閉店履歴は検索できません。'}</div>}
    <div className="content"><MapPanel items={items} selected={selected} distance={distance} onSelect={select}/><aside className="sidebar"><div className="sidebar-heading"><div><span className="eyebrow">CLOSURE SIGNALS</span><h2>店舗一覧 <small>{total} 件</small></h2></div><div className="legend">地図上のロゴで店舗を表示</div></div>
      {loading&&<div className="state-message">読み込み中…</div>}{error&&<div className="state-message error">{error}</div>}{!loading&&!error&&items.length===0&&<div className="state-message"><strong>{entirelyBeforeCollection?'指定期間の履歴は未収集です':'該当する店舗はありません'}</strong><p>{demoMode?'架空のデモデータ内に該当する店舗はありません。状態・距離・期間を変更してください。':entirelyBeforeCollection?`${date(health?.first_snapshot)}より前の店舗差分は保存されていません。`:health?.snapshot_count===0?'全国の初回スナップショットを収集中です。':health?.snapshot_day_count===1?'観測日はまだ初回の1日分です。以前の閉店は判定できず、今後の取得差分から検知します。':'選択した状態・距離・期間に該当する閉店・消失イベントはありません。'}</p></div>}
      <div className="result-list">{items.map(item=><button type="button" key={item.id} className={`result-card ${selectedId===item.id?'selected':''}`} onClick={()=>select(item.id)}><div className="card-top"><span className={`brand-badge ${item.store.brand_family==='LAWSON'?'lawson':'family'}`}>{item.store.brand_family==='LAWSON'?lawsonVariantLabels[lawsonVariantFromName(item.store.canonical_name)]:'FamilyMart'}</span><span className={`status-badge ${item.status==='CLOSED_CONFIRMED'?'confirmed':''}`}>{labels[item.status]??item.status}</span></div><h3>{item.store.canonical_name}</h3><p className="card-city">{item.store.prefecture} {item.store.city}</p><div className="card-meta"><span>検知 {date(item.detected_at)}</span><strong>{item.distance_m==null?'距離未算出':`${Math.round(item.distance_m)}m`}</strong></div><div className="card-footer">収録店内の最寄り {item.nearest_seven?.canonical_name??'未取得'} <span>›</span></div></button>)}</div>
      {total>100&&<div className="pagination"><button disabled={page===0} onClick={()=>setPage(page-1)}>前へ</button><span>{page+1} / {Math.ceil(total/100)}</span><button disabled={(page+1)*100>=total} onClick={()=>setPage(page+1)}>次へ</button></div>}
    </aside></div>
    {selected&&<div className="detail-backdrop" onClick={()=>setSelectedId(null)}><section className="detail-panel" role="dialog" aria-label="店舗詳細" onClick={event=>event.stopPropagation()}><button className="close" aria-label="詳細を閉じる" onClick={()=>setSelectedId(null)}>×</button><span className="eyebrow">STORE DETAIL</span><h2>{selected.store.canonical_name}</h2><div className="detail-tags"><span className="brand-badge">{selected.store.brand_family==='LAWSON'?lawsonVariantLabels[lawsonVariantFromName(selected.store.canonical_name)]:'FamilyMart'}</span><span className={`status-badge ${selected.status==='CLOSED_CONFIRMED'?'confirmed':''}`}>{labels[selected.status]??selected.status}</span><span>確度 {selected.confidence}</span></div><div className="detail-scroll"><h3>閉店・消失情報</h3><dl><dt>閉店日</dt><dd>{date(selected.closure_date)}</dd><dt>検知日</dt><dd>{date(selected.detected_at)}</dd><dt>最終確認</dt><dd>{date(selected.last_seen_at)}</dd><dt>理由</dt><dd>{selected.reason??'未確認'}</dd></dl><h3>閉店前の店舗情報</h3><dl><dt>当時の店舗名</dt><dd>{selected.last_observation.observed_name}</dd><dt>住所</dt><dd>{selected.last_observation.observed_address}</dd><dt>位置</dt><dd>{selected.last_observation.lat.toFixed(6)}, {selected.last_observation.lng.toFixed(6)}</dd><dt>ソース</dt><dd>{selected.last_observation.source}</dd><dt>観測日</dt><dd>{date(selected.last_observation.observed_at)}</dd>{selected.last_observation.source_category&&<><dt>分類</dt><dd>{selected.last_observation.source_category}</dd></>}{selected.last_observation.licenses?.length&&<><dt>ライセンス</dt><dd>{selected.last_observation.licenses.join('、')}</dd></>}{selected.last_observation.attributions?.length&&<><dt>出典表記</dt><dd>{selected.last_observation.attributions.join('、')}</dd></>}</dl><h3>収録店内の最寄りセブン-イレブン</h3><div className="seven-box"><strong>{selected.nearest_seven?.canonical_name??'未取得'}</strong><p>{selected.nearest_seven?.address}</p><b>{selected.distance_m?.toFixed(1)??'—'}m</b> ・ 100m基準で{selected.within_100m?'範囲内':'範囲外'}</div><a className="external-map-link" href={googleMapsSearchUrl(selected.store)} target="_blank" rel="noopener noreferrer">Googleマップで店舗を照合 ↗</a><h3>根拠</h3>{detail?.evidence?.length?detail.evidence.map(e=><div key={e.id} className="evidence"><b>{e.title}</b><span>{e.evidence_type} · {e.evidence_date??'日付不明'}</span><p>{e.summary}</p>{e.source_ref&&<a href={e.source_ref} target="_blank" rel="noreferrer">参照先 ↗</a>}</div>):<p className="muted">根拠は未登録です。消失だけでは閉店を意味しません。</p>}</div></section></div>}
    </>}
    <footer>消失は閉店確定を意味しません。{demoMode?'デモデータは架空の店舗・根拠です。':''} POI: <a href="https://docs.openpoiapi.com/" target="_blank" rel="noreferrer">OpenPOI API</a> / Overture Maps · 地図: OpenFreeMap / OpenStreetMap contributors</footer>
  </main>;
}
