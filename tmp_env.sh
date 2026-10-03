pid=$(pgrep -f 'uwsgi.*API' | head -1)
echo PID=$pid
printf '%s\n' 'budimas' | sudo -S sh -c "tr '\0' '\n' < /proc/$pid/environ | grep -E 'DB_|SQLALCHEMY|DATABASE|POSTGRES|AI_DB'"
