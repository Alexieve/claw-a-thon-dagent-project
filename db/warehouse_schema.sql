-- Air data warehouse schema (NEW_DATABASE_URL).
-- Tách biệt với db/schema.sql (metadata DB cũ). Cột để LOWERCASE, không quote, nên SQL
-- không-quote do LLM sinh (vd reqDate, userID) tự fold về lowercase và khớp.
-- NGUỒN SỰ THẬT là agent_core/data_warehouse.py:WAREHOUSE_TABLES — file này là bản mirror
-- để chạy/đọc bằng psql. scripts/load_air_data.py sinh DDL trực tiếp từ WAREHOUSE_TABLES.

create table if not exists payment_air (
  transid BIGINT,
  appid INTEGER,
  amount BIGINT,
  apptransid TEXT,
  appuser TEXT,
  reqdate TIMESTAMP,
  userid BIGINT,
  round_type TEXT,
  origin TEXT,
  dest TEXT,
  route TEXT,
  flight_type TEXT,
  in_out_bound TEXT,
  flight_date DATE,
  booking_window INTEGER,
  booking_window_group TEXT,
  etl_date TIMESTAMP
);

create table if not exists search_air (
  user_id BIGINT,
  activity_time TIMESTAMP,
  product_line TEXT,
  departure TEXT,
  dest TEXT,
  route TEXT,
  departure_date DATE,
  trip_type TEXT,
  search_date DATE,
  search_day_in_week TEXT,
  departure_day_in_week TEXT,
  day_diff INTEGER,
  user_search_group TEXT,
  etl_date TIMESTAMP
);
