import os
from sqlalchemy import create_engine, text
pg_user = os.environ.get('AI_DB_USER') or os.environ.get('DB_USER') or 'postgres'
pg_pass = os.environ.get('AI_DB_PASS') or os.environ.get('DB_PASS') or ''
pg_host = os.environ.get('AI_DB_HOST') or os.environ.get('DB_HOST') or '127.0.0.1'
pg_port = os.environ.get('AI_DB_PORT') or os.environ.get('DB_PORT') or '5432'
pg_name = os.environ.get('AI_DB_NAME') or os.environ.get('DB_NAME') or 'budimas_dev'
engine = create_engine(f'postgresql+pg8000://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_name}')
with engine.connect() as conn:
    print('current_database', conn.execute(text('select current_database()')).scalar())
    print('current_schema', conn.execute(text('select current_schema()')).scalar())
    rows = conn.execute(text("""
        select table_schema, table_name
        from information_schema.tables
        where table_name ilike '%purchase%' or table_name ilike '%order%'
        order by table_schema, table_name
        limit 100
    """)).fetchall()
    for row in rows:
        print(row)
