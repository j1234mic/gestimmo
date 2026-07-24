import sys
sys.path.insert(0, '.')
from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            sender_id INTEGER REFERENCES owners(id) ON DELETE SET NULL,
            sender_type VARCHAR(20) DEFAULT 'admin',
            recipient_id INTEGER REFERENCES owners(id) ON DELETE SET NULL,
            recipient_type VARCHAR(20) DEFAULT 'owner',
            subject VARCHAR(255),
            content TEXT,
            attachment_url VARCHAR(500),
            is_read BOOLEAN DEFAULT FALSE,
            read_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """))
    conn.commit()
    print('✅ Table messages créée !')