-- Stage 3: run once on a new project as postgres. No destructive resets.
begin;
create schema audit;
create schema collector_private;
revoke all on schema audit, collector_private from public;
create table audit.participants (
 participant_id text primary key check (participant_id ~ '^p[0-9]{2,4}$'),
 created_at timestamptz not null default now()
);
create table audit.raw_response_manifest (
 response_id text primary key check (response_id ~ '^[a-f0-9]{64}$'),
 participant_id text not null references audit.participants,
 provider text not null check (provider in ('google_health','whoop','fitbit_export')),
 dataset text not null, endpoint text not null, requested_range jsonb not null,
 requested_resolution text not null, collected_at timestamptz not null,
 object_location text not null,
 content_sha256 text not null check (content_sha256 ~ '^[a-f0-9]{64}$'),
 compressed_bytes bigint not null check (compressed_bytes >= 0), manifest jsonb not null,
 unique (response_id, participant_id, provider, dataset)
);
create table audit.records (
 participant_id text not null references audit.participants, provider text not null,
 dataset text not null, record_key text not null, content_sha256 text not null,
 record jsonb not null, -- Complete normalized context; original lives in Storage.
 source_response_id text not null, collected_at timestamptz not null,
 primary key (participant_id, provider, dataset, record_key),
 foreign key (source_response_id,participant_id,provider,dataset)
 references audit.raw_response_manifest(response_id,participant_id,provider,dataset)
);
create table audit.measurements (
 participant_id text not null, provider text not null, dataset text not null,
 record_key text not null, metric text not null, value numeric, unit text,
 vendor_value jsonb, vendor_unit text,
 value_kind text not null check (value_kind in ('measurement','vendor_calculation','vendor_summary','vendor_score','sentra_calculation','unknown')),
 availability text not null, measured_at timestamptz, interval_start timestamptz, interval_end timestamptz,
 civil_date jsonb, timestamp_basis text not null, vendor_time jsonb not null,
 collected_at timestamptz not null, resolution_seconds numeric, resolution_description text not null,
 source_response_id text not null, source_pointer text not null,
 primary key (participant_id,provider,dataset,record_key,metric),
 foreign key (participant_id,provider,dataset,record_key) references audit.records,
 foreign key (source_response_id,participant_id,provider,dataset)
 references audit.raw_response_manifest(response_id,participant_id,provider,dataset),
 check (interval_end is null or interval_start is null or interval_end >= interval_start)
);
create table audit.sessions (
 participant_id text not null, provider text not null, dataset text not null,
 record_key text not null, session_type text not null check (session_type in ('sleep','workout','cycle')),
 started_at timestamptz, ended_at timestamptz, score_state text, provisional boolean not null,
 primary key (participant_id,provider,dataset,record_key),
 foreign key (participant_id,provider,dataset,record_key) references audit.records
);
create table audit.collection_runs (
 run_id text not null, participant_id text not null references audit.participants,
 provider text not null, started_at timestamptz not null, finished_at timestamptz,
 status text not null, details jsonb not null,
 primary key (run_id,participant_id,provider)
);
create table audit.connection_state (
 participant_id text not null references audit.participants, provider text not null, dataset text not null,
 authorization_status text not null, last_success_at timestamptz, covered_intervals jsonb not null,
 continuation_state jsonb not null, updated_at timestamptz not null default now(),
 primary key (participant_id,provider,dataset)
);
create table collector_private.provider_credentials (
 participant_id text not null references audit.participants, provider text not null,
 encrypted_token_bundle bytea not null, encryption_key_version text not null,
 version bigint not null default 1, refresh_status text not null,
 updated_at timestamptz not null default now(), primary key (participant_id,provider)
);
create table collector_private.storage_members (
 user_id uuid primary key references auth.users,
 access_kind text not null check (access_kind in ('collector','viewer'))
);
create table collector_private.egress_budget (
 month date primary key, baseline_bytes bigint not null check (baseline_bytes >= 0),
 reserved_bytes bigint not null default 0 check (reserved_bytes >= 0), verified_at timestamptz not null
);
create index measurements_filters on audit.measurements(participant_id,provider,metric,measured_at);
create index measurements_intervals on audit.measurements(participant_id,provider,interval_start);
create index manifests_hash on audit.raw_response_manifest(participant_id,provider,content_sha256);
create index runs_status on audit.collection_runs(participant_id,provider,started_at);
commit;
