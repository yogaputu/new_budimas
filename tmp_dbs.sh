printf '%s\n' 'budimas' | sudo -S -u postgres psql -Atqc "select datname from pg_database where datistemplate=false order by datname;"
