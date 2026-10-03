#!/usr/bin/env python3
import datetime as dt
import hashlib
import os
import sqlite3
import subprocess


NAME = "Budimas Legacy Transaction Sync"
CRON_ID = hashlib.md5(NAME.encode("utf-8")).hexdigest()
CRON_DIR = "/www/server/cron"
CRON_FILE = os.path.join(CRON_DIR, CRON_ID)
CRON_LOG = CRON_FILE + ".log"
PANEL_DB = "/www/server/panel/data/default.db"
COMMAND = "/root/sync_legacy_recent_transactions.sh"


SCRIPT_BODY = f"""#!/bin/bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH
echo $$ > {CRON_FILE}.pl
{COMMAND}
echo "----------------------------------------------------------------------------"
endDate=`date +"%Y-%m-%d %H:%M:%S"`
echo "★[$endDate] Successful"
echo "----------------------------------------------------------------------------"
if [[ "$1" != "start" ]]; then
    btpython /www/server/panel/script/log_task_analyzer.py {CRON_LOG}
fi
rm -f {CRON_FILE}.pl
"""


def install_db_record():
    conn = sqlite3.connect(PANEL_DB)
    try:
        cur = conn.cursor()
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("SELECT id FROM crontab WHERE name=?", (NAME,))
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                UPDATE crontab
                SET type='day',
                    where1='',
                    where_hour=2,
                    where_minute=15,
                    echo=?,
                    status=1,
                    save=3,
                    backupTo='localhost',
                    sName='',
                    sBody=?,
                    addtime=COALESCE(NULLIF(addtime,''), ?)
                WHERE id=?
                """,
                (CRON_ID, COMMAND, now, row[0]),
            )
        else:
            cur.execute(
                """
                INSERT INTO crontab
                    (name, type, where1, where_hour, where_minute, echo, addtime, status,
                     save, backupTo, sName, sBody, sType, urladdress, save_local, notice,
                     notice_channel, db_type, split_type, split_value, rname, type_id,
                     keyword, post_param, flock, time_set, backup_mode, db_backup_path,
                     time_type, special_time, log_cut_path, user_agent, version, table_list,
                     result, second)
                VALUES
                    (?, 'day', '', 2, 15, ?, ?, 1,
                     3, 'localhost', '', ?, '', '', 0, 0,
                     '', '', '', 0, '', NULL,
                     '', '', 0, '', '', '',
                     '', '', '', '', '', '',
                     1, '')
                """,
                (NAME, CRON_ID, now, COMMAND),
            )
        conn.commit()
    finally:
        conn.close()


def install_cron_file():
    os.makedirs(CRON_DIR, exist_ok=True)
    with open(CRON_FILE, "w", encoding="utf-8") as fh:
        fh.write(SCRIPT_BODY)
    os.chmod(CRON_FILE, 0o750)
    open(CRON_LOG, "a", encoding="utf-8").close()


def install_system_crontab():
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    lines = result.stdout.splitlines() if result.returncode == 0 else []
    filtered = [
        line for line in lines
        if "/root/sync_legacy_recent_transactions.sh" not in line
        and CRON_ID not in line
    ]
    filtered.append(f"15 2 * * *  {CRON_FILE} >> {CRON_LOG} 2>&1")
    payload = "\n".join(filtered).rstrip() + "\n"
    subprocess.run(["crontab", "-"], input=payload, text=True, check=True)


def main():
    install_cron_file()
    install_db_record()
    install_system_crontab()
    print(f"installed_name={NAME}")
    print(f"cron_id={CRON_ID}")
    print(f"cron_file={CRON_FILE}")
    print(f"cron_log={CRON_LOG}")


if __name__ == "__main__":
    main()
