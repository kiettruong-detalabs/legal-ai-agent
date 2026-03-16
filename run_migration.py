import os
#!/usr/bin/env python3
"""Run database migration"""
import psycopg2
import sys

DB_CONFIG = {
    "host": os.getenv("SUPABASE_DB_HOST", "localhost"),
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": os.getenv("SUPABASE_DB_PASSWORD", ""),
    "sslmode": "require"
}

def run_migration():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        with open('migrations/add_admin_features.sql', 'r') as f:
            sql = f.read()
        
        # Execute each statement
        for statement in sql.split(';'):
            if statement.strip():
                try:
                    cur.execute(statement)
                    conn.commit()
                    print(f"✓ Executed: {statement[:50]}...")
                except Exception as e:
                    print(f"✗ Error: {e}")
                    conn.rollback()
        
        cur.close()
        conn.close()
        print("\n✓ Migration completed!")
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()
