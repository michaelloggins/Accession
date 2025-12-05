#!/bin/bash

# Install ODBC Driver for SQL Server
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev

# Run database migrations
echo "Running database migrations..."
python -m alembic upgrade head || echo "Migration failed or already up to date"

# Seed initial data (only runs if tables are empty, skips if data exists)
echo "Seeding initial data..."
cd /home/site/wwwroot
python scripts/seed_user.py || echo "User seeding skipped or failed"
echo "n" | python scripts/seed_species.py || echo "Species seeding skipped or failed"
echo "no" | python scripts/seed_tests.py || echo "Tests seeding skipped or failed"
python scripts/seed_break_glass_admin.py || echo "Break glass admin seeding skipped or failed"

# Start the application
gunicorn --bind=0.0.0.0:8000 --workers=4 --timeout=120 app.main:app -k uvicorn.workers.UvicornWorker
