printf '%s\n' 'budimas' | sudo -S cp /tmp/PurchaseOrder.py /www/wwwroot/budimas/API/apps/services/PurchaseOrder.py
printf '%s\n' 'budimas' | sudo -S chown www:www /www/wwwroot/budimas/API/apps/services/PurchaseOrder.py
printf '%s\n' 'budimas' | sudo -S /www/server/python_manager/versions/3.12.0/bin/uwsgi --reload /www/server/python_project/vhost/pids/API.pid
