create table if not exists raw_events (
  id text primary key,
  source_type text not null,
  stakeholder text not null default '',
  team text not null default '',
  document_id text not null default '',
  status text not null default 'parsed',
  raw_text text not null default '',
  created_at timestamptz not null,
  payload jsonb not null
);

create table if not exists knowledge_records (
  id text primary key,
  name text not null,
  status text not null default 'approved',
  owner text not null default '',
  domain text not null default '',
  version integer not null default 1,
  updated_at timestamptz not null,
  payload jsonb not null
);

create unique index if not exists knowledge_records_name_approved_idx
  on knowledge_records (lower(name))
  where status = 'approved';

create index if not exists knowledge_records_payload_gin_idx
  on knowledge_records using gin (payload);

create table if not exists knowledge_candidates (
  id text primary key,
  name text not null,
  status text not null,
  target_knowledge_id text references knowledge_records(id) on delete set null,
  proposed_by text not null default '',
  original_owner text not null default '',
  created_at timestamptz not null,
  payload jsonb not null
);

create index if not exists knowledge_candidates_status_idx
  on knowledge_candidates (status);

create table if not exists teaching_sessions (
  id text primary key,
  status text not null,
  stakeholder text not null default '',
  team text not null default '',
  owner text not null default '',
  created_at timestamptz not null,
  updated_at timestamptz not null,
  payload jsonb not null
);

create index if not exists teaching_sessions_status_idx
  on teaching_sessions (status);

create table if not exists document_chunks (
  id text primary key,
  document_id text not null,
  chunk_index integer not null default 0,
  title text not null default '',
  created_at timestamptz not null,
  payload jsonb not null
);

create index if not exists document_chunks_document_id_idx
  on document_chunks (document_id);
