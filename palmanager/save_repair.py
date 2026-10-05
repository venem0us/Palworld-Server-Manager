"""Targeted expedition recovery. All edits are validated offline before installation."""
import copy, hashlib, struct

FIELD = 'MapObjectConcreteInstanceIdAssignedToExpedition'
ZERO = '00000000-0000-0000-0000-000000000000'
MAX_SAVE = 256 * 1024 * 1024
MAX_RAW = 512 * 1024 * 1024

def digest(data):
    return hashlib.sha256(data).hexdigest()

def unpack(data):
    if len(data) < 12 or len(data) > MAX_SAVE:
        raise ValueError('Save is empty or exceeds the supported 256 MB limit')
    size, compressed = struct.unpack_from('<II', data)
    if data[8:12] != b'PlM1' or compressed != len(data)-12 or not 0 < size <= MAX_RAW:
        raise ValueError('Only validated PlM1 world saves up to 512 MB uncompressed are supported')
    import ooz
    raw = ooz.decompress(data[12:], size)
    if len(raw) != size or not raw.startswith(b'GVAS'):
        raise ValueError('Save decompression validation failed')
    return raw

def pack(raw):
    import ooz
    compressed = ooz.compress(9, 4, raw, len(raw))
    result = struct.pack('<II', len(raw), len(compressed)) + b'PlM1' + compressed
    if unpack(result) != raw:
        raise ValueError('Compressed save verification failed; original save retained')
    return result

def value(props, key):
    return props.get(key, {}).get('value')

def record_id(rec):
    # Palworld's map key is BOTH player UID and instance GUID. Migrated worlds
    # can retain old-host entries sharing an instance GUID with a current entry.
    return str(value(rec['key'],'PlayerUId')) + '/' + str(value(rec['key'],'InstanceId'))

def parse_raw(raw):
    from palworld_save_tools.gvas import GvasFile
    from palworld_save_tools.paltypes import PALWORLD_TYPE_HINTS
    from palworld_save_tools.rawdata import character
    custom = {'.worldSaveData.CharacterSaveParameterMap.Value.RawData': (character.decode, character.encode)}
    gvas = GvasFile.read(raw, PALWORLD_TYPE_HINTS, custom)
    return gvas, custom

def index(gvas):
    from palworld_save_tools.archive import UUID
    world = gvas.properties['worldSaveData']['value']
    records = world['CharacterSaveParameterMap']['value']
    players, pals, seen, duplicates = {}, {}, set(), set()
    # ConcreteModel starts with its instance GUID; inspect only Expedition buildings.
    buildings = set()
    for obj in world['MapObjectSaveData']['value']['values']:
        if value(obj, 'MapObjectId') != 'Expedition':
            continue
        raw = bytes(obj['ConcreteModel']['value']['RawData']['value']['values'])
        if len(raw) < 32:
            raise ValueError('An expedition building has an unsupported record; repair blocked')
        buildings.add(str(UUID(raw[:16])))
    for rec in records:
        param = rec['value']['RawData']['value']['object']['SaveParameter']
        if param['struct_type'] != 'PalIndividualCharacterSaveParameter':
            raise ValueError('Unsupported character save record')
        props = param['value']
        instance = record_id(rec)
        if instance in seen:
            duplicates.add(instance)
        seen.add(instance)
        if value(props, 'IsPlayer'):
            owner = str(value(rec['key'], 'PlayerUId'))
            if owner in players:
                raise ValueError('Duplicate player ownership records; repair blocked')
            players[owner] = value(props, 'NickName') or owner
            continue
        assignment = str(value(props, FIELD))
        if assignment in ('None', ZERO):
            continue
        owner = str(value(props, 'OwnerPlayerUId'))
        pals[instance] = dict(id=instance, owner=owner, species=value(props, 'CharacterID') or 'Unknown',
                              name=value(props, 'NickName') or '', expedition=assignment,
                              stale=assignment not in buildings, props=props)
    for pal in pals.values():
        pal['player'] = players.get(pal['owner'], 'Unknown owner')
        pal['recoverable'] = pal['stale'] and pal['owner'] in players and pal['owner'] != ZERO and pal['id'] not in duplicates
    return pals

def public_rows(pals):
    return [{k:v for k,v in row.items() if k != 'props'} for row in pals.values()]

def inspect(data):
    raw = unpack(data)
    gvas, custom = parse_raw(raw)
    rows = public_rows(index(gvas))
    # The writer mutates decoded custom records, so this object is not reused.
    if gvas.write(custom) != raw:
        raise ValueError('This save cannot round-trip without unrelated changes; repair blocked')
    return {'hash':digest(data), 'pals':rows, 'roundtrip':True}

def repair(data, owner, expected):
    """Expected maps selected instance IDs to their previewed expedition GUIDs."""
    if not owner or owner == ZERO or not expected:
        raise ValueError('Choose a player and at least one Pal')
    raw = unpack(data)
    baseline, custom = parse_raw(raw)
    if baseline.write(custom) != raw:
        raise ValueError('No-change round-trip failed; original save retained')
    gvas, custom = parse_raw(raw)
    pals = index(gvas)
    selected = []
    for instance, expedition in expected.items():
        pal = pals.get(instance)
        if not pal or pal['owner'] != owner or pal['expedition'] != expedition or not pal['recoverable']:
            raise ValueError('Selection changed, ownership is ambiguous, or expedition still exists. Scan again.')
        selected.append(pal)
    removed = {pal['id']: pal['props'].pop(FIELD) for pal in selected}
    edited = gvas.write(custom)
    verify, custom = parse_raw(edited)
    if any(instance in index(verify) for instance in expected):
        raise ValueError('Expedition removal verification failed')
    # Put only the removed fields back and require EXACT original GVAS bytes.
    # Preserve original field order from a fresh parse when restoring.
    original, _ = parse_raw(raw)
    original_records = original.properties['worldSaveData']['value']['CharacterSaveParameterMap']['value']
    original_order = {record_id(r): list(r['value']['RawData']['value']['object']['SaveParameter']['value']) for r in original_records}
    for rec in verify.properties['worldSaveData']['value']['CharacterSaveParameterMap']['value']:
        instance = record_id(rec)
        if instance in removed:
            param = rec['value']['RawData']['value']['object']['SaveParameter']
            props = param['value'];props[FIELD] = removed[instance]
            param['value'] = {k:props[k] for k in original_order[instance]}
    if verify.write(custom) != raw:
        raise ValueError('Unrelated save bytes changed; repair blocked')
    result = pack(edited)
    return result, {'recovered':len(selected), 'before':digest(data), 'after':digest(result),
                    'player':selected[0]['player'], 'ids':list(expected)}
