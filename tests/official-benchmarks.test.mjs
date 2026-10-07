import test from 'node:test';
import assert from 'node:assert/strict';
import { officialBrandBenchmarks, officialBrandReferences } from '../apps/web/lib/official-benchmarks.ts';
import { prefectures } from '../apps/web/lib/prefectures.ts';

test('official prefecture benchmarks cover all prefectures and match their published totals', () => {
  for (const [family, benchmark] of Object.entries(officialBrandBenchmarks)) {
    assert.equal(Object.keys(benchmark.prefecture_counts).length, 47, `${family} prefecture count`);
    assert.deepEqual(Object.keys(benchmark.prefecture_counts).sort(), [...prefectures].sort(), `${family} prefecture names`);
    assert.equal(Object.values(benchmark.prefecture_counts).reduce((sum, count) => sum + count, 0), benchmark.prefecture_total, `${family} prefecture sum`);
  }
});

test('health references select same-area counts and retain each publisher date', () => {
  const national = officialBrandReferences();
  assert.equal(national.FAMILY_MART.count, 16455);
  assert.equal(national.LAWSON.count, 14630);
  assert.equal(national.SEVEN_ELEVEN.count, 21956);

  const kanagawa = officialBrandReferences('神奈川県');
  assert.equal(kanagawa.FAMILY_MART.count, 1009);
  assert.equal(kanagawa.LAWSON.count, 1067);
  assert.equal(kanagawa.LAWSON.as_of, '2026-02-28');
  assert.equal(kanagawa.SEVEN_ELEVEN.count, 1540);
});
