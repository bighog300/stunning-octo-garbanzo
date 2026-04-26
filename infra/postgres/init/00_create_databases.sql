SELECT 'CREATE DATABASE artio'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'artio')\gexec

SELECT 'CREATE DATABASE airflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec

SELECT 'CREATE DATABASE superset'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'superset')\gexec
