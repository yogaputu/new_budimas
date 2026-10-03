TOKEN=$(printf '%s\n' 'budimas' | sudo -S -u postgres psql -d budimas_dev -Atqc "SELECT tokens FROM public.users WHERE id=1")
curl -sS -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8099/api/akuntansi/get-hutang?id_cabang=5&id_perusahaan=1&principal=5&no-paginate=true&field=id&order=desc' > /tmp/hutang_response_np.json
python3 - <<'PY'
from pathlib import Path
data = Path('/tmp/hutang_response_np.json').read_text()
print('FOUND_0011', 'TP-20260616143832' in data)
idx = data.find('TP-20260616143832')
print(data[max(0, idx-250):idx+250] if idx >= 0 else data[:800])
PY