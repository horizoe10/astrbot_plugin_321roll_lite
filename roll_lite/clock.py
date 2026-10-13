"""Commit hosted time and the calendar's appointments together."""
from .commands import UserError
from .storage import dumps, loads, new_id, now


def commit(app, db, room, actor_ref, source, target, activity):
    if target is None:
        return
    current = loads(room['clock_json'])
    if current != source:
        raise UserError('团桌时间在正文生成后已变化，请重写这段正文后再发布。')
    records = [dict(r, ref=r['id'], document=loads(r['document_json'])) for r in db.execute(
        "SELECT * FROM records WHERE room_id=? AND kind IN ('calendar','appointment','deadline')", (room['id'],))]
    try:
        operations = app.engine.clock_changes(records, actor_ref, current, target, activity[:200])
    except ValueError as exc:
        raise UserError('这段正文的时间与当前日历不一致，请重写后再发布。') from exc
    for op in operations:
        if op['op'] == 'create':
            db.execute("INSERT INTO records(id,room_id,seq,play,kind,state,audience,members_json,document_json,created_by,"
                       "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (new_id('rec'), room['id'], app.store.next_seq(db, room['id']), 'playCalendar', op['kind'],
                        op['state'], op.get('audience','room'), dumps(op.get('members',[])), dumps(op['document']),
                        actor_ref, now(), now()))
        elif op['op'] == 'update':
            if db.execute("UPDATE records SET state=?,document_json=?,revision=revision+1,updated_at=? "
                          "WHERE id=? AND room_id=? AND revision=?",
                          (op['state'], dumps(op['document']), now(), op['ref'], room['id'], op['revision'])).rowcount != 1:
                raise UserError('日历记录已变化，请重写这段正文后再发布。')
    db.execute('UPDATE rooms SET clock_json=? WHERE id=?', (dumps(target),room['id']))
    if operations:
        slots=('清晨','白天','傍晚','夜晚')
        app.store.add_event(db, room['id'], 'play', f"时间推进至第 {target['day']} 日 · {slots[target['slot']]}",
                            actor_id=actor_ref, data={'clock_before':source,'clock_after':target})
