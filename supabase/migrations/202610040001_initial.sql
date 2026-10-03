create extension if not exists pgcrypto;
create extension if not exists postgis;

create table if not exists snapshot_runs (
  id uuid primary key, snapshot_key text not null unique, source text not null,
  prefecture text not null check (prefecture = '神奈川県'),
  started_at timestamptz not null, finished_at timestamptz,
  status text not null check (status in ('running','succeeded','failed')),
  store_count integer not null default 0, error_message text, metadata jsonb not null default '{}'
);
create table if not exists stores (
  id uuid primary key, brand_family text not null check (brand_family in ('FAMILY_MART','LAWSON','SEVEN_ELEVEN')),
  canonical_name text not null, normalized_name text not null, address text not null,
  normalized_address text not null, prefecture text not null check (prefecture = '神奈川県'), city text not null,
  lat double precision not null, lng double precision not null,
  location geography(Point,4326) generated always as (ST_SetSRID(ST_MakePoint(lng,lat),4326)::geography) stored,
  source text not null, source_store_id text, first_seen_at timestamptz not null,
  last_seen_at timestamptz not null, current_presence text not null,
  missing_count integer not null default 0, created_at timestamptz not null, updated_at timestamptz not null
);
create index if not exists stores_location_gix on stores using gist(location);
create index if not exists stores_brand_prefecture_presence_idx on stores(brand_family,prefecture,current_presence);
create table if not exists store_observations (
  id uuid primary key, snapshot_run_id uuid not null references snapshot_runs(id),
  store_id uuid not null references stores(id), source text not null, source_store_id text,
  observed_name text not null, observed_address text not null, lat double precision not null,
  lng double precision not null, source_category text, source_business_type text,
  licenses jsonb not null default '[]', attributions jsonb not null default '[]',
  raw_payload jsonb not null default '{}', fetched_at timestamptz not null, observed_at timestamptz not null,
  unique(snapshot_run_id, store_id, source)
);
create index if not exists observations_store_time_idx on store_observations(store_id,observed_at desc);
create table if not exists closure_events (
  id uuid primary key, store_id uuid not null references stores(id),
  detected_at timestamptz not null, last_seen_at timestamptz not null,
  status text not null check (status in ('MISSING','CLOSED_SUSPECTED','CLOSED_CONFIRMED','RELOCATED','TEMPORARY_CLOSED','RENAMED','DATA_ISSUE','REOPENED')),
  closure_date date, reason text, confidence text not null check (confidence in ('LOW','MEDIUM','HIGH')),
  nearest_seven_store_id uuid references stores(id), distance_m numeric,
  within_100m boolean not null default false,
  last_observation_id uuid not null references store_observations(id),
  created_at timestamptz not null, updated_at timestamptz not null
);
create unique index if not exists one_active_event_per_store on closure_events(store_id) where status <> 'REOPENED';
create index if not exists events_status_detected_idx on closure_events(status,detected_at desc);
create table if not exists event_seven_neighbors (
  closure_event_id uuid not null references closure_events(id),
  seven_store_id uuid not null references stores(id),
  distance_m numeric not null,
  primary key(closure_event_id,seven_store_id)
);
create table if not exists event_evidence (
  id uuid primary key, closure_event_id uuid not null references closure_events(id),
  evidence_type text not null, title text not null, source_ref text,
  evidence_date date, summary text not null, supports_closure boolean not null,
  created_at timestamptz not null
);
create table if not exists brand_aliases (
  id uuid primary key default gen_random_uuid(), brand_family text not null,
  alias text not null unique, enabled boolean not null default true
);
create table if not exists app_state (
  singleton boolean primary key default true check (singleton), state jsonb not null
);
insert into brand_aliases(brand_family,alias) values
('FAMILY_MART','ファミリーマート'),('FAMILY_MART','ファミマ!!'),('FAMILY_MART','ファミマ'),('FAMILY_MART','FamilyMart'),
('LAWSON','ローソン'),('LAWSON','LAWSON'),('LAWSON','ローソンストア100'),('LAWSON','ナチュラルローソン'),('LAWSON','ローソン・スリーエフ'),('LAWSON','LAWSON+toks'),
('SEVEN_ELEVEN','セブン-イレブン'),('SEVEN_ELEVEN','セブンイレブン'),('SEVEN_ELEVEN','Seven-Eleven'),('SEVEN_ELEVEN','7-Eleven')
on conflict(alias) do nothing;

-- Browser clients have no direct table grants. Server-side PostgreSQL queries provide read APIs.
alter table snapshot_runs enable row level security;
alter table stores enable row level security;
alter table store_observations enable row level security;
alter table closure_events enable row level security;
alter table event_seven_neighbors enable row level security;
alter table event_evidence enable row level security;
alter table brand_aliases enable row level security;
alter table app_state enable row level security;
revoke all on all tables in schema public from anon, authenticated;

create or replace function refresh_event_nearest(p_event_id uuid)
returns void language plpgsql as $$
begin
  update closure_events e set
    nearest_seven_store_id = nearest.id,
    distance_m = nearest.distance_m,
    within_100m = coalesce(ST_DWithin(competitor.location, nearest.location, 100), false)
  from stores competitor
  left join lateral (
    select seven.id, seven.location, ST_Distance(competitor.location, seven.location) as distance_m
    from stores seven
    where seven.brand_family = 'SEVEN_ELEVEN' and seven.current_presence = 'PRESENT'
    order by ST_Distance(competitor.location, seven.location) limit 1
  ) nearest on true
  where e.id = p_event_id and competitor.id = e.store_id;
  delete from event_seven_neighbors where closure_event_id = p_event_id;
  insert into event_seven_neighbors(closure_event_id,seven_store_id,distance_m)
  select p_event_id, seven.id, ST_Distance(competitor.location,seven.location)
  from closure_events e join stores competitor on competitor.id=e.store_id
  join stores seven on seven.brand_family='SEVEN_ELEVEN' and seven.current_presence='PRESENT'
  where e.id=p_event_id and ST_DWithin(competitor.location,seven.location,100);
end $$;
