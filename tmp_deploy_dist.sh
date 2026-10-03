set -e
rm -rf /tmp/dist-20260616145013
mkdir -p /tmp/dist-20260616145013
printf '%s\n' 'budimas' | sudo -S tar -xzf /tmp/dist-20260616145013.tgz -C /tmp/dist-20260616145013
printf '%s\n' 'budimas' | sudo -S rm -rf /www/wwwroot/budimas-new.com/dist
printf '%s\n' 'budimas' | sudo -S mkdir -p /www/wwwroot/budimas-new.com/dist
printf '%s\n' 'budimas' | sudo -S cp -a /tmp/dist-20260616145013/. /www/wwwroot/budimas-new.com/dist/
printf '%s\n' 'budimas' | sudo -S chown -R www:www /www/wwwroot/budimas-new.com/dist