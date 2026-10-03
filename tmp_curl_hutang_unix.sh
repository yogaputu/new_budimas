TOKEN=$(printf '%s\n' 'budimas' | sudo -S -u postgres psql -d budimas_dev -Atqc "SELECT tokens FROM public.users WHERE id=1")
curl -sS -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8099/api/akuntansi/get-hutang?id_cabang=5&id_perusahaan=1&principal=5' > /tmp/hutang_response.json
python3 - <<'PY'
from pathlib import Path
data = Path('/tmp/hutang_response.json').read_text()
print(data[:1200])
print('FOUND', 'TP-20260616143832' in data)
PY