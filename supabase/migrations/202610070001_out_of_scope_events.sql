alter table closure_events drop constraint if exists closure_events_status_check;
alter table closure_events add constraint closure_events_status_check
  check (status in ('MISSING','CLOSED_SUSPECTED','CLOSED_CONFIRMED','RELOCATED','TEMPORARY_CLOSED','RENAMED','DATA_ISSUE','REOPENED','OUT_OF_SCOPE'));

drop index if exists one_active_event_per_store;
create unique index one_active_event_per_store on closure_events(store_id)
  where status not in ('REOPENED','OUT_OF_SCOPE');
