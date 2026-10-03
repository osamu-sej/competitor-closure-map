insert into brand_aliases(brand_family,alias) values
('FAMILY_MART','ファミリーマート'),('FAMILY_MART','ファミマ!!'),('FAMILY_MART','ファミマ'),('FAMILY_MART','FamilyMart'),
('LAWSON','ローソン'),('LAWSON','LAWSON'),('LAWSON','ローソンストア100'),('LAWSON','ナチュラルローソン'),('LAWSON','ローソン・スリーエフ'),('LAWSON','LAWSON+toks'),
('SEVEN_ELEVEN','セブン-イレブン'),('SEVEN_ELEVEN','セブンイレブン'),('SEVEN_ELEVEN','Seven-Eleven'),('SEVEN_ELEVEN','7-Eleven')
on conflict(alias) do nothing;
