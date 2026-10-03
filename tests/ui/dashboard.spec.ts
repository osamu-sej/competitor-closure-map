import { test, expect } from '@playwright/test';

test('filters keep list and map aligned and detail uses last observation', async ({page})=>{
  await page.goto('/');
  await expect(page.locator('.result-card')).toHaveCount(1);
  await expect(page.locator('.store-marker')).toHaveCount(1);
  await page.getByLabel('ブランド').selectOption('FAMILY_MART');
  await expect(page.locator('.result-card')).toHaveCount(0);
  await expect(page.locator('.store-marker')).toHaveCount(0);
  await page.getByLabel('ブランド').selectOption('ALL');
  await expect(page.locator('.result-card')).toHaveCount(1);
  await page.locator('.result-card').click();
  await expect(page.getByRole('dialog',{name:'店舗詳細'})).toBeVisible();
  await expect(page.getByText('神奈川県相模原市中央区中央1-1-2')).toBeVisible();
  await expect(page.locator('.map-distance')).toContainText('45m');
  await page.getByLabel('詳細を閉じる').click();
  await page.locator('.store-marker').click();
  await expect(page.getByRole('dialog',{name:'店舗詳細'})).toBeVisible();
  await page.getByLabel('詳細を閉じる').click();
  await page.getByLabel('距離').selectOption('50');
  await expect(page.locator('.result-card')).toHaveCount(1);
  await page.getByLabel('状態').selectOption('MISSING');
  await expect(page.locator('.result-card')).toHaveCount(0);
});
