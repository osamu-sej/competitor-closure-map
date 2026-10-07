/**
 * Published chain counts used as comparison points, not as store records.
 * Prefecture counts have independent publication dates and may be older than
 * the national totals. Keep the date and source beside every benchmark.
 */
export const officialBrandBenchmarks = {
  FAMILY_MART: {
    count: 16455,
    as_of: '2026-08-31',
    source: 'https://www.family.co.jp/company/familymart/monthly_sales/flash.html',
    prefecture_as_of: '2026-08-31',
    prefecture_source: 'https://www.family.co.jp/company/familymart/store.html',
    prefecture_total: 16455,
    prefecture_counts: {
      '北海道':255,'青森県':180,'岩手県':188,'宮城県':320,'秋田県':121,'山形県':123,'福島県':176,
      '茨城県':328,'栃木県':220,'群馬県':113,'埼玉県':772,'千葉県':649,'東京都':2443,'神奈川県':1009,
      '新潟県':163,'富山県':150,'石川県':245,'福井県':150,'山梨県':82,'長野県':263,
      '岐阜県':342,'静岡県':509,'愛知県':1625,'三重県':398,'滋賀県':156,'京都府':329,'大阪府':1363,
      '兵庫県':518,'奈良県':149,'和歌山県':106,'鳥取県':66,'島根県':62,'岡山県':229,'広島県':249,
      '山口県':91,'徳島県':77,'香川県':117,'愛媛県':208,'高知県':98,'福岡県':551,'佐賀県':77,
      '長崎県':153,'熊本県':193,'大分県':117,'宮崎県':134,'鹿児島県':250,'沖縄県':338,
    },
  },
  LAWSON: {
    count: 14630,
    as_of: '2026-08-31',
    source: 'https://www.lawson.co.jp/company/ir/financial/monthly/index.html',
    prefecture_as_of: '2026-02-28',
    prefecture_source: 'https://www.lawson.co.jp/company/corporate/data/sales/',
    prefecture_total: 14697,
    prefecture_counts: {
      '北海道':730,'青森県':279,'岩手県':180,'宮城県':264,'秋田県':180,'山形県':106,'福島県':166,
      '茨城県':214,'栃木県':197,'群馬県':234,'埼玉県':683,'千葉県':589,'東京都':1639,'神奈川県':1067,
      '新潟県':226,'富山県':171,'石川県':105,'福井県':109,'山梨県':135,'長野県':173,
      '岐阜県':175,'静岡県':280,'愛知県':707,'三重県':142,'滋賀県':149,'京都府':327,'大阪府':1200,
      '兵庫県':692,'奈良県':139,'和歌山県':156,'鳥取県':135,'島根県':137,'岡山県':248,'広島県':315,
      '山口県':135,'徳島県':135,'香川県':134,'愛媛県':209,'高知県':138,'福岡県':535,'佐賀県':78,
      '長崎県':130,'熊本県':169,'大分県':203,'宮崎県':111,'鹿児島県':202,'沖縄県':269,
    },
  },
  SEVEN_ELEVEN: {
    count: 21956,
    as_of: '2026-09-30',
    source: 'https://www.sej.co.jp/company/tenpo.html',
    prefecture_as_of: '2026-09-30',
    prefecture_source: 'https://www.sej.co.jp/company/tenpo.html',
    prefecture_total: 21956,
    prefecture_counts: {
      '北海道':991,'青森県':112,'岩手県':166,'宮城県':445,'秋田県':127,'山形県':187,'福島県':457,
      '茨城県':649,'栃木県':483,'群馬県':494,'埼玉県':1274,'千葉県':1196,'東京都':2943,'神奈川県':1540,
      '新潟県':430,'富山県':139,'石川県':139,'福井県':73,'山梨県':209,'長野県':452,'岐阜県':194,
      '静岡県':763,'愛知県':1070,'三重県':178,'滋賀県':221,'京都府':351,'大阪府':1317,'兵庫県':694,
      '奈良県':137,'和歌山県':87,'鳥取県':63,'島根県':74,'岡山県':320,'広島県':595,'山口県':313,
      '徳島県':83,'香川県':123,'愛媛県':141,'高知県':52,'福岡県':1061,'佐賀県':193,'長崎県':210,
      '熊本県':386,'大分県':190,'宮崎県':209,'鹿児島県':214,'沖縄県':211,
    },
  },
} as const;

export function officialBrandReferences(prefecture = ''): Record<string, {count:number|null;as_of:string;source:string}> {
  return Object.fromEntries(Object.entries(officialBrandBenchmarks).map(([family, benchmark]) => [family, {
    count: prefecture ? benchmark.prefecture_counts[prefecture as keyof typeof benchmark.prefecture_counts] ?? null : benchmark.count,
    as_of: prefecture ? benchmark.prefecture_as_of : benchmark.as_of,
    source: prefecture ? benchmark.prefecture_source : benchmark.source,
  }]));
}
