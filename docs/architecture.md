# Architecture

```text
Fixture / CSV / OpenPOI -> StoreSource -> normalize + match -> snapshot diff
                                                     |
                                            PostgreSQL transaction
                                                     |
                      snapshot_runs / stores / observations / events / evidence
                                                     |
                                   PostGIS nearest Seven and 100m test
                                                     |
                            Next.js read routes -> MapLibre + list + detail
```

`store_observations` are append-only and a closure event keeps `last_observation_id` from immediately before disappearance. A source adapter failure aborts before state mutation. `snapshot_key` makes retries idempotent. Matching is conservative: stable source ID, then normalized address within brand, then 30m and name similarity. Uncertain duplicates remain separate.

The browser never receives database credentials or raw payloads. Read routes use a server-side PostgreSQL connection in DB mode. Fixture mode reads an ignored local JSON projection generated from the same collector state machine. All application tables have RLS enabled, and anonymous/authenticated direct grants are revoked.

The current UI fetches a paged list with the same filters applied to map markers. A separate bbox route supports viewport queries. At larger event counts, the UI should request bbox pages as the map moves.
