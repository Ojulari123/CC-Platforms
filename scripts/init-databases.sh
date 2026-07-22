#!/bin/bash
# Runs once on first postgres container start. Creates one DB per service so
# they can't reach each other's data (CLAUDE.md rule 3).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    CREATE DATABASE identity;
    CREATE DATABASE pulse;
    CREATE DATABASE forge;
EOSQL
