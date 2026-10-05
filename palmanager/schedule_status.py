"""Compare local schedules to the worker's live configuration, not a publish flag."""
def signature(schedule,timezone):
    return ({k:schedule.get(k) for k in ('action','mode','minutes','at','enabled','message')},timezone)

def publication(schedule,profile,state):
    if not state or state.get('error'):return 'Not verified'
    if not state.get('installed'):return 'Not published'
    health=state.get('health')
    if not isinstance(health,dict) or 'schedules' not in health or 'schedule_timezone' not in health:return 'Not verified'
    matches=[s for s in health['schedules'] if s.get('id')==schedule.get('id')]
    if not matches:return 'Not published'
    if len(matches)!=1:return 'Not verified'
    return 'Published' if signature(schedule,profile.get('schedule_timezone','UTC'))==signature(matches[0],health['schedule_timezone']) else 'Changes pending'

def remote_only(profile,state):
    health=(state or {}).get('health') or {}
    if (state or {}).get('error'):return []
    ids={s['id'] for s in profile.get('schedules',[])}
    return [s for s in health.get('schedules',[]) if s.get('id') not in ids]
