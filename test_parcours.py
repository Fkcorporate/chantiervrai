import io, re, sys, os, shutil, time
from datetime import datetime, timezone
BASE = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
inst = os.path.join(BASE, 'instance')
shutil.rmtree(inst, ignore_errors=True)
import app as A
from PIL import Image

def jpg(lat, lng, when, color=(200,100,50)):
    im = Image.new('RGB', (64, 48), color)
    ex = Image.Exif()
    def dms(x):
        x = abs(x); d = int(x); m = int((x-d)*60); s = round(((x-d)*60-m)*60, 4)
        return (float(d), float(m), s)
    ex[0x8825] = {1: 'N' if lat >= 0 else 'S', 2: dms(lat), 3: 'E' if lng >= 0 else 'W', 4: dms(lng)}
    ex.get_ifd(0x8769)[0x9003] = when.strftime('%Y:%m:%d %H:%M:%S')
    b = io.BytesIO(); im.save(b, 'JPEG', exif=ex.tobytes()); return b.getvalue()

def tok(c, url):
    r = c.get(url); m = re.search(r'name="csrf" value="([^"]+)"', r.get_data(as_text=True)); return m.group(1)

A.app.config['TESTING'] = True
own, chef = A.app.test_client(), A.app.test_client()
t = tok(own, '/inscription')
r = own.post('/inscription', data=dict(csrf=t, terms='1', role='proprio', name='Aminata K', email='a@x.ci', password='Bingerville-2026'))
assert r.status_code == 302, r.status_code
t = tok(own, '/chantiers/nouveau')
data = dict(csrf=t, name='Villa R+1', address='Bingerville', lat='5.3521', lng='-3.8892', radius='100')
for i, (n, a, *_) in enumerate(A.DEFAULT_STEPS): data[f'step_name_{i}'] = n; data[f'step_amount_{i}'] = str(a)
r = own.post('/chantiers/nouveau', data=data); assert r.status_code == 302; pid = int(r.headers['Location'].rstrip('/').split('/')[-1])
page = own.get(f'/chantiers/{pid}').get_data(as_text=True)
code = re.search(r'class="code">(\w+)<', page).group(1); print('invite', code)

t = tok(chef, '/inscription')
chef.post('/inscription', data=dict(csrf=t, terms='1', role='chef', name='Koffi', email='k@x.ci', password='Koffi-Chef-2026', phone='0700000000'))
t = tok(chef, '/')
r = chef.post('/rejoindre', data=dict(csrf=t, code=code)); assert r.status_code == 302
# owner cannot upload, outsider blocked
assert own.post(f'/chantiers/{pid}/preuves', data=dict(csrf=tok(own, '/'))).status_code == 403

nowu = datetime.now(timezone.utc).replace(tzinfo=None)
def up(img, **extra):
    t = tok(chef, f'/chantiers/{pid}')
    d = dict(csrf=t, tz_offset='0', note='test', photo=(io.BytesIO(img), 'p.jpg')); d.update(extra)
    r = chef.post(f'/chantiers/{pid}/preuves', data=d, content_type='multipart/form-data', follow_redirects=True)
    return r.get_data(as_text=True)

good = jpg(5.3522, -3.8891, nowu)
h = up(good); assert 'Preuve vérifiée et envoyée' in h, h[:3000]; print('good ok')
h = up(good); assert 'déjà envoyée' in h; print('dup refused')
h = up(jpg(5.40, -3.90, nowu, (1,2,3))); assert 'du terrain' in h; print('far refused')
h = up(jpg(5.3522, -3.8891, datetime(2025,1,1), (9,9,9))); assert 'ancienne' in h; print('old refused')
h = up(jpg(5.3522, -3.8891, nowu, (7,7,7)), lat='5.50', lng='-3.80'); assert 'incohérentes' in h; print('incoherent refused')

t = tok(chef, f'/chantiers/{pid}')
step1 = A.sqlite3.connect(A.DB_PATH).execute('select id from steps where project_id=? order by position', (pid,)).fetchone()[0]
r = chef.post(f'/chantiers/{pid}/etapes/{step1}/declarer', data=dict(csrf=t), follow_redirects=True)
assert 'déclarée terminée' in r.get_data(as_text=True)
t = tok(own, f'/chantiers/{pid}?onglet=etapes')
r = own.post(f'/chantiers/{pid}/etapes/{step1}/valider', data=dict(csrf=t, pay_ref='WAVE123', override='1'), follow_redirects=True)
h = r.get_data(as_text=True); assert 'Étape validée' in h and 'WAVE123' in h; print('paid ok')
home = own.get(f'/chantiers/{pid}').get_data(as_text=True)
print('verified', re.search(r'Avancement vérifié</b><b[^>]*>(\d+) %', home).group(1), '% ; refused alert', '4 preuve(s) refusée(s)' in home)
for tab in ['preuves','satellite']: assert own.get(f'/chantiers/{pid}?onglet={tab}').status_code == 200
assert chef.get(f'/chantiers/{pid}?onglet=preuves').status_code == 200
assert own.get('/photos/1').status_code == 200
anon = A.app.test_client(); assert anon.get('/photos/1').status_code == 302
# CSRF missing
assert own.post('/deconnexion').status_code == 400
print('ALL OK')
