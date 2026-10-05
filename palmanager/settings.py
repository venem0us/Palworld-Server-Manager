"""Lossless Unreal OptionSettings editor. Shared with the remote helper."""
import re

SECTION = '[/Script/Pal.PalGameWorldSettings]'

def span(text):
    sections = list(re.finditer(r'^\s*\[/Script/Pal\.PalGameWorldSettings\]\s*$', text, re.M))
    if len(sections) != 1:
        raise ValueError('Expected one PalGameWorldSettings section; resolve missing or duplicate sections')
    section = sections[0]
    end = re.search(r'^\s*\[', text[section.end():], re.M)
    limit = section.end() + end.start() if end else len(text)
    matches = list(re.finditer(r'^[ \t]*OptionSettings\s*=\s*\(', text[section.end():limit], re.M))
    if len(matches) != 1:
        raise ValueError('Expected exactly one OptionSettings entry; resolve duplicate or missing entries first')
    start = section.end() + matches[0].end()
    depth, quoted, escaped = 1, False, False
    for i in range(start, limit):
        ch = text[i]
        if escaped: escaped = False; continue
        if quoted and ch == '\\': escaped = True; continue
        if ch == '"': quoted = not quoted
        if not quoted:
            if ch == '(': depth += 1
            if ch == ')':
                depth -= 1
                if depth == 0: return start, i
    raise ValueError('Unbalanced OptionSettings')

def parts(value):
    result, start, depth, quoted, escaped = [], 0, 0, False, False
    for i, ch in enumerate(value):
        if escaped: escaped = False; continue
        if quoted and ch == '\\': escaped = True; continue
        if ch == '"': quoted = not quoted
        if not quoted:
            if ch == '(': depth += 1
            elif ch == ')': depth -= 1
            elif ch == ',' and depth == 0: result.append(value[start:i]); start = i + 1
            if depth < 0: raise ValueError('Unbalanced value')
    if quoted or depth or escaped: raise ValueError('Unbalanced value')
    result.append(value[start:])
    return result

def parse(text):
    a, b = span(text)
    result = {}
    for item in parts(text[a:b]):
        if not item.strip(): continue
        if '=' not in item: raise ValueError('Setting lacks =')
        key, value = item.split('=', 1)
        key = key.strip()
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) or key in result:
            raise ValueError('Invalid or duplicate setting: ' + key)
        result[key] = value.strip()
    return result

def validate(key, value, original=''):
    if not isinstance(value, str) or any(c in value for c in '\r\n\x00'):
        raise ValueError(key + ': invalid value')
    if len(parts(value)) != 1: raise ValueError(key + ': quote text containing commas')
    if '=' in value and not (value.startswith('"') or value.startswith('(')):
        raise ValueError(key + ': invalid scalar')
    if original.lower() in ('true', 'false') and value.lower() not in ('true', 'false'):
        raise ValueError(key + ': choose True or False')
    if original.startswith('"') and not (value.startswith('"') and value.endswith('"')):
        raise ValueError(key + ': text must be quoted')
    if re.fullmatch(r'-?\d+(\.\d+)?', original):
        if not re.fullmatch(r'-?\d+(\.\d+)?', value): raise ValueError(key + ': enter a number')
    if key in ('PublicPort','RCONPort','RESTAPIPort') and not 1 <= int(value) <= 65535:
        raise ValueError(key + ': must be 1–65535')

def patch(text, changes, defaults=None):
    defaults = defaults or {}
    current = parse(text)
    for key, value in changes.items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key): raise ValueError('Invalid key')
        validate(key, value, current.get(key, defaults.get(key, '')))
    a, b = span(text)
    chunks = parts(text[a:b]); remaining = dict(changes)
    for i, chunk in enumerate(chunks):
        if '=' not in chunk: continue
        key = chunk.split('=', 1)[0].strip()
        if key not in remaining: continue
        value = remaining.pop(key)
        m = re.match(r'([^=]+=\s*)(.*?)(\s*)$', chunk, re.S)
        chunks[i] = m.group(1) + value + m.group(3)
    if remaining:
        if len(chunks) == 1 and not chunks[0].strip(): chunks = []
        chunks.extend(k + '=' + v for k, v in remaining.items())
    result = text[:a] + ','.join(chunks) + text[b:]
    parse(result)
    return result

def group(key):
    if any(x in key for x in ('Password','ServerName','ServerDescription','REST','RCON','Port','PublicIP','Crossplay','Region','Auth','BanList','LogFormat','ClientMod','Chat','Voice')): return 'Server & network'
    if any(x in key for x in ('PvP','Hardcore','Death','Respawn','Friendly','PlayerToPlayer')): return 'Combat & difficulty'
    if any(x in key for x in ('Base','Build','Guild','Work','Farm','Container','Replicate')): return 'Bases & guilds'
    if key.startswith('Pal') or 'Palbox' in key or 'Random' in key or 'Predator' in key: return 'Pals & breeding'
    if key.startswith('Player') or 'EnhanceStat' in key or key == 'ExpRate': return 'Players & progression'
    if any(x in key for x in ('Item','Drop','Collection','Supply','Equipment','Fishing')): return 'Resources & items'
    return 'World & advanced'

def label(key):
    name = key[1:] if key.startswith('b') and len(key)>1 and key[1].isupper() else key
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', name)

PRESETS = {
    'Relaxed co-op (suggested)': {'ExpRate':'2.000000','CollectionDropRate':'2.000000','DeathPenalty':'None','PalEggDefaultHatchingTime':'0.500000'},
    'Low resource load (suggested)': {'PalSpawnNumRate':'1.000000','BaseCampWorkerMaxNum':'15','DropItemMaxNum':'1500','PhysicsActiveDropItemMaxNum':'500','ServerReplicatePawnCullDistance':'10000.000000'},
}
