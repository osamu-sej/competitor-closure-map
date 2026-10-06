import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseFilters } from '../apps/web/lib/filters.ts';
import { addLawsonVariantCount, emptyLawsonVariantCounts, lawsonVariantFromName } from '../apps/web/lib/lawson-variant.ts';

test('brand selections and distance thresholds are accepted by the read API', () => {
  assert.deepEqual(parseFilters(new URLSearchParams()).brands, ['FAMILY_MART', 'LAWSON']);
  assert.deepEqual(parseFilters(new URLSearchParams('brands=LAWSON,FAMILY_MART')).brands, ['LAWSON', 'FAMILY_MART']);
  assert.deepEqual(parseFilters(new URLSearchParams('brands=LAWSON')).brands, ['LAWSON']);
  assert.deepEqual(parseFilters(new URLSearchParams('brands=')).brands, []);
  assert.deepEqual(parseFilters(new URLSearchParams('brand=FAMILY_MART')).brands, ['FAMILY_MART']);
  assert.equal(parseFilters(new URLSearchParams('distance=500')).distance, 500);
  assert.equal(parseFilters(new URLSearchParams('distance=1000')).distance, 1000);
  assert.equal(parseFilters(new URLSearchParams('prefecture=北海道')).prefecture, '北海道');
  assert.equal(parseFilters(new URLSearchParams('prefecture=invalid')).prefecture, '');
});

test('Lawson sub-brands are counted separately from names while retaining a family total', () => {
  const counts = emptyLawsonVariantCounts();
  for (const name of [
    'ローソン 相模原中央店',
    'ローソンストア１００ 横浜店',
    'ナチュラルローソン 渋谷店',
    'LAWSON+toks 駅構内店',
    'ローソン・スリーエフ 川崎店',
  ]) addLawsonVariantCount(counts, name);

  assert.equal(lawsonVariantFromName('NATURAL LAWSON Ebisu'), 'NATURAL_LAWSON');
  assert.equal(counts.LAWSON, 1);
  assert.equal(counts.LAWSON_STORE_100, 1);
  assert.equal(counts.NATURAL_LAWSON, 1);
  assert.equal(counts.LAWSON_TOKS, 1);
  assert.equal(counts.LAWSON_THREE_F, 1);
  assert.equal(Object.values(counts).reduce((sum, value) => sum + value, 0), 5);
});
