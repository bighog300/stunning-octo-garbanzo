DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'artio') THEN
      CREATE ROLE artio LOGIN PASSWORD 'artio';
   END IF;

   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'airflow') THEN
      CREATE ROLE airflow LOGIN PASSWORD 'airflow';
   END IF;
END
$$;

GRANT ALL PRIVILEGES ON DATABASE artio TO artio;
GRANT ALL PRIVILEGES ON DATABASE airflow TO airflow;
