-- Extensions utiles
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Configuration
ALTER DATABASE immo_db SET timezone TO 'Europe/Paris';

SELECT '✅ PostgreSQL initialisé avec succès !' as status;
