import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from collector.engine import add_evidence, apply_snapshot, new_state, promotion_status, within_distance
from collector.matching import matches
from collector.model import RawStore
from collector.normalization import brand_family, normalize_address, normalize_name
from collector.prefectures import PREFECTURES
from collector.sources.fixture import FixtureSource
from collector.sources.openpoi import KEYWORDS, OpenPoiSource


ROOT = Path(__file__).resolve().parent.parent


class InlineSource:
    def __init__(self, rows): self.rows = rows
    def fetch_stores(self, prefecture, brand): return [row for row in self.rows if brand_family(row.name) == brand]


class CollectorTests(unittest.TestCase):
    def test_normalization_and_matching(self):
        self.assertEqual(brand_family('ナチュラルローソン 横浜店'), 'LAWSON')
        self.assertEqual(brand_family('FamilyMart 横浜店'), 'FAMILY_MART')
        self.assertEqual(brand_family('セブン-イレブン 横浜店'), 'SEVEN_ELEVEN')
        self.assertIsNone(brand_family('Amazon ロッカー - ローソン_厚木寿町'))
        self.assertEqual(normalize_name('ローソン　横浜店'), '横浜')
        self.assertEqual(normalize_address('神奈川県横浜市中区1丁目２番３号'), '横浜市中区1-2-3')
        raw=RawStore('ローソン 新横浜店','神奈川県横浜市港北区新横浜1-1-1',35.5,139.6,source_store_id='a')
        old={'brand_family':'LAWSON','source':'fixture','source_store_id':'a','normalized_address':'x','normalized_name':'unrelated','lat':35,'lng':139}
        self.assertTrue(matches(raw,old,'LAWSON'))
        self.assertFalse(matches(raw,{**old,'source_store_id':'b'},'LAWSON'))

    def test_fixture_diff_idempotency_last_observation_and_evidence(self):
        state=new_state()
        first=ROOT/'fixtures/snapshot_001.json'; second=ROOT/'fixtures/snapshot_002.json'
        apply_snapshot(state,FixtureSource(first),'one','2026-06-01T00:00:00Z')
        self.assertEqual(len(state['events']),0)
        run=apply_snapshot(state,FixtureSource(second),'two','2026-06-15T00:00:00Z')
        self.assertEqual(run['metadata']['missing'],1)
        self.assertEqual(len(state['events']),1)
        event=state['events'][0]
        self.assertEqual(event['status'],'MISSING')
        self.assertTrue(44 < event['distance_m'] < 46)
        self.assertTrue(event['within_100m'])
        self.assertEqual(next(o for o in state['observations'] if o['id']==event['last_observation_id'])['observed_name'],'ローソン 相模原中央店')
        self.assertEqual(next(s for s in state['stores'] if s['id']==event['nearest_seven_store_id'])['brand_family'],'SEVEN_ELEVEN')
        self.assertEqual(len([e for e in state['events'] if next(s for s in state['stores'] if s['id']==e['store_id'])['brand_family']=='FAMILY_MART']),0)
        apply_snapshot(state,FixtureSource(second),'two','2026-06-15T00:00:00Z')
        self.assertEqual(len(state['events']),1)
        evidence=json.loads((ROOT/'fixtures/evidence.json').read_text())
        add_evidence(state,evidence.pop('store_name'),evidence)
        self.assertEqual(event['status'],'CLOSED_CONFIRMED')
        self.assertEqual(event['closure_date'],'2026-06-10')

    def test_repeated_missing_and_reopened(self):
        state=new_state(); first=FixtureSource(ROOT/'fixtures/snapshot_001.json');second=FixtureSource(ROOT/'fixtures/snapshot_002.json')
        apply_snapshot(state,first,'one','2026-06-01T00:00:00Z')
        apply_snapshot(state,second,'two','2026-06-15T00:00:00Z')
        apply_snapshot(state,second,'three','2026-06-20T00:00:00Z')
        self.assertEqual(state['events'][0]['status'],'CLOSED_SUSPECTED')
        apply_snapshot(state,first,'four','2026-06-25T00:00:00Z')
        self.assertEqual(state['events'][0]['status'],'REOPENED')
        self.assertEqual(promotion_status(1,1),'CLOSED_SUSPECTED')

    def test_boundary_and_outside_fixture(self):
        self.assertTrue(within_distance(99.9,100))
        self.assertTrue(within_distance(100.0,100))
        self.assertFalse(within_distance(100.1,100))
        base=[RawStore('セブン-イレブン A','神奈川県相模原市中央区1',35.4,139.4),RawStore('ファミリーマート Z','神奈川県相模原市中央区2',35.4,139.40119)]
        state=new_state();apply_snapshot(state,InlineSource(base),'one','2026-01-01T00:00:00Z');apply_snapshot(state,InlineSource(base[:1]),'two','2026-01-02T00:00:00Z')
        self.assertEqual(len(state['events']),1)
        self.assertTrue(107 < state['events'][0]['distance_m'] < 109)
        self.assertFalse(state['events'][0]['within_100m'])

    def test_openpoi_saturated_bbox_recurses_and_deduplicates(self):
        source=OpenPoiSource(limit=2,max_depth=2)
        row={'name':'ローソン A','address':'神奈川県横浜市中区1','lat':35.4,'lng':139.4,'prefecture':'神奈川県','city':'横浜市中区','source':'overture','category':'convenience_store','licenses':['Apache-2.0'],'attributions':['Overture Maps Foundation']}
        with patch.object(source,'_search',side_effect=[[row,row],[row],[],[],[],[],[]]) as search:
            rows=source.fetch_stores('神奈川県','LAWSON')
        self.assertEqual(len(rows),1)
        self.assertGreaterEqual(search.call_count,5)
        self.assertEqual(rows[0].licenses,['Apache-2.0'])

    def test_lawson_search_filters_other_sources_before_deduplication(self):
        source=OpenPoiSource()
        first={'name':'ローソン 横浜店','address':'','lat':35.4,'lng':139.4,'prefecture':'神奈川県','source':'overture','category':'convenience_store','licenses':['Apache-2.0']}
        second={**first,'address':'神奈川県横浜市中区1','lng':139.4001,'source':'jff','category':'restaurant','licenses':['CC-BY-4.0']}
        with patch.object(source,'_partition',side_effect=[[first],[second]]):
            rows=source.fetch_stores('神奈川県','LAWSON')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].address,'')
        self.assertEqual(rows[0].source,'overture')
        self.assertEqual(rows[0].source_category,'convenience_store')
        self.assertEqual(rows[0].licenses,['Apache-2.0'])

    def test_lawson_search_keeps_only_overture_convenience_store_pois(self):
        source=OpenPoiSource()
        rows=[
            RawStore('ローソン 横浜店','神奈川県横浜市中区1',35.4,139.4,source='overture',source_category='convenience_store'),
            RawStore('ローソン銀行','神奈川県横浜市中区2',35.4,139.401,source='overture',source_category='service_other'),
            RawStore('ローソン 横浜店','神奈川県横浜市中区1',35.4,139.4,source='jff',source_category='restaurant'),
        ]
        with patch.object(source,'_fetch_family',return_value=rows):
            found=source.fetch_stores('神奈川県','LAWSON')
        self.assertEqual(found,[rows[0]])

    def test_lawson_policy_suppresses_legacy_candidates_without_false_closures(self):
        active=RawStore('ローソン 横浜店','神奈川県横浜市中区1',35.4,139.4,source='overture',source_category='convenience_store')
        legacy_active=RawStore(active.name,active.address,active.lat,active.lng,source='openpoi',source_category='convenience_store')
        bank=RawStore('ローソン銀行','神奈川県横浜市中区2',35.4,139.401,source='openpoi',source_category='service_other')
        permit=RawStore('ローソン 許可記録','神奈川県横浜市中区3',35.4,139.402,source='openpoi',source_category='restaurant')
        state=new_state()
        source=InlineSource([legacy_active,bank,permit])
        apply_snapshot(state,source,'legacy','2026-10-01T00:00:00Z')
        source.rows=[legacy_active]
        apply_snapshot(state,source,'legacy-missing','2026-10-02T00:00:00Z')
        self.assertEqual({event['status'] for event in state['events']},{'MISSING'})
        source.rows=[active]
        source.managed_presence_families={'LAWSON'}
        source.coverage_policy_version='lawson-overture-convenience-store-v1'
        run=apply_snapshot(state,source,'curated','2026-10-08T00:00:00Z')
        stores={store['source']+':'+str(store['source_category']):store for store in state['stores']}
        self.assertEqual(stores['overture:convenience_store']['current_presence'],'PRESENT')
        self.assertEqual(stores['openpoi:service_other']['current_presence'],'SUPPRESSED')
        self.assertEqual(stores['openpoi:restaurant']['current_presence'],'SUPPRESSED')
        self.assertEqual(run['metadata']['missing'],0)
        self.assertEqual(run['metadata']['out_of_scope'],2)
        self.assertEqual({event['status'] for event in state['events']},{'OUT_OF_SCOPE'})

    def test_openpoi_retry_uses_complete_local_cache(self):
        row=RawStore('ローソン 横浜店','神奈川県横浜市中区1',35.4,139.4,source='overture',source_category='convenience_store')
        with TemporaryDirectory() as directory:
            first=OpenPoiSource(cache_key='week-1',cache_dir=Path(directory))
            with patch.object(first,'_fetch_family',return_value=[row]) as fetch:
                self.assertEqual(first.fetch_stores('神奈川県','LAWSON'),[row])
                self.assertEqual(fetch.call_count,1)
            retry=OpenPoiSource(cache_key='week-1',cache_dir=Path(directory))
            with patch.object(retry,'_fetch_family',side_effect=AssertionError('network should not be used')):
                self.assertEqual(retry.fetch_stores('神奈川県','LAWSON'),[row])

    def test_openpoi_keyword_change_invalidates_cache(self):
        row=RawStore('ローソン 横浜店','神奈川県横浜市中区1',35.4,139.4,source='overture',source_category='convenience_store')
        with TemporaryDirectory() as directory:
            first=OpenPoiSource(cache_key='week-1',cache_dir=Path(directory))
            with patch.object(first,'_fetch_family',return_value=[row]):
                first.fetch_stores('神奈川県','LAWSON')
            changed=OpenPoiSource(cache_key='week-1',cache_dir=Path(directory))
            with patch.dict(KEYWORDS,{'LAWSON':KEYWORDS['LAWSON']+['LAWSON STORE']},clear=False):
                with patch.object(changed,'_fetch_family',return_value=[row]) as fetch:
                    changed.fetch_stores('神奈川県','LAWSON')
                    self.assertEqual(fetch.call_count,1)

    def test_openpoi_legacy_lawson_cache_is_refetched_for_policy_change(self):
        with TemporaryDirectory() as directory:
            source=OpenPoiSource(cache_key='same-key',cache_dir=Path(directory))
            cache_path=source._cache_path('LAWSON')
            cache_path.parent.mkdir(parents=True,exist_ok=True)
            cache_path.write_text(json.dumps({"version":2,"base_url":source.base_url,"keywords":KEYWORDS['LAWSON'],"stores":[{"name":"ローソン 横浜店","address":"神奈川県横浜市中区1","lat":35.4,"lng":139.4,"prefecture":"神奈川県","source":"openpoi","source_category":"convenience_store"}]}),encoding='utf-8')
            current=RawStore('ローソン 横浜店','神奈川県横浜市中区1',35.4,139.4,source='overture',source_category='convenience_store')
            with patch.object(source,'_fetch_family',return_value=[current]) as fetch:
                self.assertEqual(source.fetch_stores('神奈川県','LAWSON'),[current])
                self.assertEqual(fetch.call_count,1)

    def test_prefecture_snapshots_do_not_mark_other_prefectures_missing(self):
        kanagawa=[RawStore('ローソン 横浜店','神奈川県横浜市中区1',35.4,139.6,prefecture='神奈川県')]
        tokyo=[RawStore('ローソン 新宿店','東京都新宿区1',35.7,139.7,prefecture='東京都')]
        class RegionalSource:
            def __init__(self, rows): self.rows=rows
            def fetch_stores(self, prefecture, family):
                return [row for row in self.rows if row.prefecture==prefecture and brand_family(row.name)==family]
        state=new_state()
        source=RegionalSource(kanagawa+tokyo)
        apply_snapshot(state,source,'kanagawa-1','2026-10-01T00:00:00Z',prefecture='神奈川県')
        apply_snapshot(state,source,'tokyo-1','2026-10-01T00:00:00Z',prefecture='東京都')
        apply_snapshot(state,RegionalSource(kanagawa),'kanagawa-2','2026-10-08T00:00:00Z',prefecture='神奈川県')
        self.assertEqual(len(state['events']),0)
        self.assertEqual(len(state['runs']),3)

    def test_same_brand_shops_at_one_address_keep_identity(self):
        rows=[RawStore('ファミリーマート ルクア大阪店','大阪府大阪市北区梅田3-1-3',34.7017,135.4964,prefecture='大阪府'),
              RawStore('ファミリーマート 大阪ステーションシティ店','大阪府大阪市北区梅田3-1-3',34.7017,135.4964,prefecture='大阪府')]
        state=new_state(); source=InlineSource(rows)
        apply_snapshot(state,source,'first','2026-10-01T00:00:00Z',prefecture='大阪府')
        again=apply_snapshot(state,source,'second','2026-10-02T00:00:00Z',prefecture='大阪府')
        self.assertEqual(again['metadata']['matched'],2)
        self.assertEqual(again['metadata']['new'],0)
        self.assertEqual(again['metadata']['missing'],0)
        self.assertEqual(len(state['events']),0)

    def test_large_source_drop_aborts_without_mutating_state(self):
        class GuardedSource(InlineSource):
            guard_coverage=True
        stores=[RawStore(f'ローソン 店舗{i}',f'神奈川県横浜市中区{i}',35.4+i/1000,139.4) for i in range(40)]
        state=new_state()
        apply_snapshot(state,GuardedSource(stores),'one','2026-10-01T00:00:00Z')
        with self.assertRaisesRegex(RuntimeError,'coverage fell'):
            apply_snapshot(state,GuardedSource(stores[:30]),'two','2026-10-08T00:00:00Z')
        self.assertEqual(len(state['runs']),1)
        self.assertEqual(len(state['events']),0)

    def test_national_coverage_allows_small_regional_swing_but_blocks_national_drop(self):
        class GuardedNationwideSource(InlineSource):
            guard_coverage=True
            managed_presence_families={'LAWSON'}
            coverage_policy_version='lawson-overture-convenience-store-v1'
            def __init__(self, rows, totals):
                super().__init__(rows)
                self.totals=totals
            def coverage_counts(self): return self.totals

        prefecture='東京都'
        state=new_state()
        state['runs']=[{
            'id':f'baseline-{index}', 'snapshot_key':f'baseline-{index}',
            'source':'guardednationwide', 'prefecture':name,
            'status':'succeeded', 'finished_at':'2026-10-01T00:00:00Z',
            'metadata':{'families':{'FAMILY_MART':1000,'LAWSON':574,'SEVEN_ELEVEN':500},
                        'coverage_policy_version':'default'},
        } for index,name in enumerate(PREFECTURES)]
        regional_rows=[RawStore(f'ファミリーマート 店{i}',f'東京都住所{i}',35.0+i/100000,139.0,prefecture=prefecture) for i in range(930)]
        regional_rows += [RawStore(f'セブン-イレブン 店{i}',f'東京都七住所{i}',36.0+i/100000,140.0,prefecture=prefecture) for i in range(500)]
        tolerant=GuardedNationwideSource(regional_rows,{'FAMILY_MART':46930,'LAWSON':14224,'SEVEN_ELEVEN':23500})
        run=apply_snapshot(state,tolerant,'regional-swing','2026-10-08T00:00:00Z',prefecture=prefecture)
        self.assertEqual(run['metadata']['families']['FAMILY_MART'],930)
        self.assertEqual(run['metadata']['new'],1430)

        state=new_state()
        state['runs']=[{
            'id':f'baseline-{index}', 'snapshot_key':f'baseline-{index}',
            'source':'guardednationwide', 'prefecture':name,
            'status':'succeeded', 'finished_at':'2026-10-01T00:00:00Z',
            'metadata':{'families':{'FAMILY_MART':1000,'LAWSON':574,'SEVEN_ELEVEN':500},
                        'coverage_policy_version':'default'},
        } for index,name in enumerate(PREFECTURES)]
        incomplete=GuardedNationwideSource(regional_rows,{'FAMILY_MART':44000,'LAWSON':14224,'SEVEN_ELEVEN':23500})
        with self.assertRaisesRegex(RuntimeError,'FAMILY_MART nationwide coverage fell'):
            apply_snapshot(state,incomplete,'national-drop','2026-10-08T00:00:00Z',prefecture=prefecture)
        self.assertEqual(len(state['runs']),len(PREFECTURES))

    def test_missing_seven_is_not_used_as_nearest(self):
        near=RawStore('セブン-イレブン 近い店','神奈川県横浜市中区1',35.4,139.4)
        far=RawStore('セブン-イレブン 遠い店','神奈川県横浜市中区2',35.4,139.402)
        competitor=RawStore('ローソン 対象店','神奈川県横浜市中区3',35.4,139.4001)
        state=new_state()
        apply_snapshot(state,InlineSource([near,far,competitor]),'one','2026-10-01T00:00:00Z')
        apply_snapshot(state,InlineSource([far]),'two','2026-10-08T00:00:00Z')
        nearest=next(s for s in state['stores'] if s['id']==state['events'][0]['nearest_seven_store_id'])
        self.assertEqual(nearest['canonical_name'],far.name)
        self.assertEqual(next(s for s in state['stores'] if s['canonical_name']==near.name)['current_presence'],'MISSING')


if __name__ == '__main__': unittest.main()
