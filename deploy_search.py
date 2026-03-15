import psycopg2
import time

DB_CONFIG = {
    "host": "db.chiokotzjtjwfodryfdt.supabase.co",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "Hl120804@.,?",
    "sslmode": "require"
}

print("Connecting to Supabase...")
conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

print("Deploying new search function...")
with open('scripts/migration_search_v2.sql', 'r') as f:
    sql = f.read()
    cur.execute(sql)
    conn.commit()

print("✓ Search function deployed successfully!")
conn.close()
