#!/bin/bash

# Install ODBC Driver for SQL Server
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql17 unixodbc-dev

# Start the application
gunicorn --bind=0.0.0.0:8000 --workers=4 --timeout=120 app.main:app -k uvicorn.workers.UvicornWorker
