TOKEN=$(printf '%s\n' 'budimas' | sudo -S -u postgres psql -d budimas_dev -Atqc "SELECT tokens FROM public.users WHERE id=1")
echo '--- no filters ---'
curl -sS -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8099/api/akuntansi/get-hutang' | grep -o 'TP-20260616143832\|2026-06-16\|ENERGIZER' | head -20
echo '\n--- BMM SOLO ET filters ---'
curl -sS -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8099/api/akuntansi/get-hutang?id_cabang=5&id_perusahaan=1&principal=5' | grep -o 'TP-20260616143832\|2026-06-16\|ENERGIZER' | head -20
