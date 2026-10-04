import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseFilters } from '../apps/web/lib/filters.ts';

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
