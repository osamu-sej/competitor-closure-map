import json
import unittest
from pathlib import Path
from unittest.mock import patch

from collector.engine import add_evidence, apply_snapshot, new_state, promotion_status, within_distance
from collector.matching import matches
from collector.model import RawStore
from collector.normalization import brand_family, normalize_address, normalize_name
from collector.sources.fixture import FixtureSource
from collector.sources.openpoi import OpenPoiSource


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
        row={'name':'ローソン A','address':'神奈川県横浜市中区1','lat':35.4,'lng':139.4,'prefecture':'神奈川県','city':'横浜市中区','source':'overture','licenses':['Apache-2.0'],'attributions':['Overture Maps Foundation']}
        with patch.object(source,'_search',side_effect=[[row,row],[row],[],[],[],[],[]]) as search:
            rows=source.fetch_stores('神奈川県','LAWSON')
        self.assertEqual(len(rows),1)
        self.assertGreaterEqual(search.call_count,5)
        self.assertEqual(rows[0].licenses,['Apache-2.0'])


if __name__ == '__main__': unittest.main()
