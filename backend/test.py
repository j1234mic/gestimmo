import sys
sys.path.insert(0, '.')
from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    # Créer owner_transactions
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS owner_transactions (
            id SERIAL PRIMARY KEY,
            owner_id INTEGER NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
            property_id INTEGER,
            transaction_type VARCHAR(50) NOT NULL,
            reference VARCHAR(50) UNIQUE,
            amount FLOAT NOT NULL,
            vat_amount FLOAT DEFAULT 0,
            transaction_date DATE NOT NULL,
            period_start DATE,
            period_end DATE,
            description TEXT,
            category VARCHAR(100),
            status VARCHAR(20) DEFAULT 'completed',
            payment_method VARCHAR(50),
            document_url VARCHAR(500),
            notes TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )
    """))
    
    # Créer owner_balances
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS owner_balances (
            id SERIAL PRIMARY KEY,
            owner_id INTEGER UNIQUE NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
            current_balance FLOAT DEFAULT 0,
            total_income FLOAT DEFAULT 0,
            total_expenses FLOAT DEFAULT 0,
            total_paid FLOAT DEFAULT 0,
            last_calculated_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )
    """))
    conn.commit()
    print('✅ Tables créées avec SQL brut !')