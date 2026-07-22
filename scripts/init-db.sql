-- init-db.sql
-- PostgreSQL initialization script for Document Conversion Platform
-- This script is automatically executed on first container startup

-- Create application schema
CREATE SCHEMA IF NOT EXISTS app;

-- Grant all privileges on the app schema to the role executing this script
GRANT ALL PRIVILEGES ON SCHEMA app TO CURRENT_USER;

-- Grant usage and create privileges on schema to the role executing this script
GRANT USAGE, CREATE ON SCHEMA app TO CURRENT_USER;

-- Set default privileges for future objects in the schema
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL PRIVILEGES ON TABLES TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL PRIVILEGES ON SEQUENCES TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL PRIVILEGES ON FUNCTIONS TO CURRENT_USER;

-- Log initialization completion
DO $$
BEGIN
    RAISE NOTICE 'Database initialization completed successfully for user: %, schema: app', CURRENT_USER;
END
$$;
