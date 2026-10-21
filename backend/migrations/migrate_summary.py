from sqlalchemy import text
from backend.app.db.session import engine

with engine.connect() as conn:
    res = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'assistant_conversations'")).fetchall()
    cols = [r[0] for r in res]
    print('Existing cols in assistant_conversations:', cols)
    if 'summary' not in cols:
        conn.execute(text("ALTER TABLE assistant_conversations ADD COLUMN summary TEXT;"))
        conn.commit()
        print('Added column summary to assistant_conversations.')
    else:
        print('Column summary already exists.')
