\set ON_ERROR_STOP on
CREATE UNIQUE INDEX IF NOT EXISTS customers_id_idx ON customers (id);
CREATE UNIQUE INDEX IF NOT EXISTS movies_id_idx ON movies (id);
CREATE UNIQUE INDEX IF NOT EXISTS sessions_id_idx ON sessions (id);
CREATE INDEX IF NOT EXISTS customers_email_idx ON customers (email);
CREATE INDEX IF NOT EXISTS customers_name_idx ON customers (name);
CREATE INDEX IF NOT EXISTS customers_surname_idx ON customers (surname);
CREATE INDEX IF NOT EXISTS movies_name_idx ON movies (name);
CREATE INDEX IF NOT EXISTS movies_year_idx ON movies (year);
CREATE INDEX IF NOT EXISTS sessions_customer_id_idx ON sessions (customer_id);
CREATE INDEX IF NOT EXISTS sessions_movie_id_idx ON sessions (movie_id);
VACUUM (ANALYZE) customers;
VACUUM (ANALYZE) movies;
VACUUM (ANALYZE) sessions;
