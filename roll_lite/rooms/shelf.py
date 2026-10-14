"""Park whole tables without closing them; only one table is active in a group."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .. import messages, shared
from ..commands import Reply, UserError
from ..storage import loads, now
from . import lifecycle


def rows(c, umo):
    return c.execute("SELECT * FROM rooms WHERE umo=? AND state='shelved' ORDER BY updated_at,id", (umo,)).fetchall()


def summary(c, room):
    data = loads(room['data_json'], {}).get('shelf', {})
    players = c.execute("SELECT COUNT(*) FROM actors WHERE room_id=? AND presence<>'left'", (room['id'],)).fetchone()[0]
    rounds = c.execute("SELECT COALESCE(MAX(round),0) FROM turns WHERE room_id=?", (room['id'],)).fetchone()[0]
    return {'id': room['id'], 'title': messages.short_title(room['title']), 'name': data.get('name') or messages.short_title(room['title']),
            'act': room['act'], 'round': rounds, 'players': players,
            'scene': loads(room['scene_json'], {}).get('title', ''), 'saved_at': data.get('at', ''),
            'lobby': data.get('state') == 'lobby'}


async def listing(app, caller, args):
    with app.store.read() as c:
        tables = [summary(c, row) for row in rows(c, caller.umo)]
        active = shared.open_room(c, caller.umo)
    return Reply().say(messages.shelf_list(tables, messages.short_title(active['title']) if active else ''))


async def shelve(app, caller, args):
    room = shared.require_room(app, caller, 'lobby', 'running', 'paused')
    shared.require_host(app, caller, room)
    name = args.strip() or messages.short_title(room['title'])
    if len(name) > 40:
        raise UserError('暂存名称最多 40 个字。发送 /团 暂存 名称，或直接 /团 暂存。')
    if app.lock(room['id']).locked():
        raise UserError('这一桌正在处理行动或生成剧情，请等本次处理结束后再 /团 暂存。')
    async with app.lock(room['id']):
        with app.store.tx() as c:
            room = c.execute('SELECT * FROM rooms WHERE id=?', (room['id'],)).fetchone()
            if room['state'] not in ('lobby', 'running', 'paused'):
                raise UserError('团桌状态已变化，请刷新后再试。')
            shared.require_host(app, caller, room)
            if c.execute("SELECT 1 FROM turns WHERE room_id=? AND state='resolving'", (room['id'],)).fetchone():
                raise UserError('这一轮还在处理中，请处理完或重试后再暂存。')
            timers = loads(room['data_json'], {}).get('shelf_timers')
            if timers is None:       # Taking a paused table back off the shelf does not thaw its clocks.
                stamp = datetime.now(UTC)
                timers = {vote['id']: max(0, (datetime.fromisoformat(vote['deadline_at']) - stamp).total_seconds())
                          for vote in c.execute("SELECT id,deadline_at FROM votes WHERE room_id=? AND state='open'", (room['id'],))}
                lifecycle._set_data(c, room['id'], shelf_timers=timers)
            lifecycle.remember_roster(c, room['id'])
            lifecycle._set_data(c, room['id'], shelf={'name': name, 'state': room['state'], 'at': now()})
            c.execute("UPDATE rooms SET state='shelved' WHERE id=?", (room['id'],))
            app.store.bump_room(c, room['id'])
            app.store.add_event(c, room['id'], 'system', f'{caller.user_name} 暂存了团桌「{name}」')
            app.store.audit(c, caller.user_id, 'room.shelve', room['id'], {'name': name})
        # Pause hooks stop epilogue clocks and publicly settle any open shopping session.
        reply = await app.hooks.emit('room_paused', room_id=room['id'])
        with app.store.tx() as c:
            fresh = c.execute('SELECT * FROM rooms WHERE id=?', (room['id'],)).fetchone()
            card = messages.shelf_result(summary(c, fresh), retrieved=False)
    return reply.say(card)


async def retrieve(app, caller, args):
    token = args.strip()
    if not token:
        return await listing(app, caller, '')
    with app.store.read() as c:
        tables = rows(c, caller.umo)
        found = [r for r in tables if r['id'] == token or summary(c, r)['name'] == token]
        if not found and token.isdigit() and 1 <= int(token) <= len(tables):
            found = [tables[int(token) - 1]]
    if len(found) != 1:
        raise UserError('暂存名称有重复，请用 /团 暂存列表 中的序号取回。' if found else '没有找到本群的暂存团桌。发送 /团 暂存列表 查看。')
    target = found[0]
    shared.require_host(app, caller, target)
    async with app.lock(target['id']):
        with app.store.tx() as c:
            target = c.execute('SELECT * FROM rooms WHERE id=?', (target['id'],)).fetchone()
            shared.require_host(app, caller, target)
            active = shared.open_room(c, caller.umo)
            if active:
                raise UserError(f'本群正在使用《{messages.short_title(active["title"])}》。请先 /团 暂存 当前桌；已完结的桌可 /团 关闭，再取回旧桌。')
            if target['state'] != 'shelved':
                raise UserError('这桌已被取回，请发送 /团 状态 查看。')
            item = summary(c, target)
            state = 'lobby' if item['lobby'] else 'paused'
            c.execute('UPDATE rooms SET state=? WHERE id=?', (state, target['id']))
            lifecycle._set_data(c, target['id'], shelf=None)
            if state == 'lobby':
                lifecycle._set_data(c, target['id'], shelf_timers=None)
            app.store.bump_room(c, target['id'])
            app.store.add_event(c, target['id'], 'system', f'{caller.user_name} 取回了团桌「{item["name"]}」')
            app.store.audit(c, caller.user_id, 'room.retrieve', target['id'], {})
        reply = Reply().say(messages.shelf_result(item, retrieved=True))
        if state == 'paused':
            reply.extend(await lifecycle.resume(app, caller, ''))
    return reply


def resume_timers(c, room_id):
    room = c.execute('SELECT data_json FROM rooms WHERE id=?', (room_id,)).fetchone()
    timers = loads(room['data_json'], {}).get('shelf_timers', {})
    for vote_id, seconds in timers.items():
        c.execute("UPDATE votes SET deadline_at=? WHERE id=? AND room_id=? AND state='open'",
                  ((datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(timespec='seconds'), vote_id, room_id))
    lifecycle._set_data(c, room_id, shelf_timers=None)


def install(app):
    app.router.register('暂存', shelve, summary='保留整桌进度，腾出本群位置（主持人）', usage='/团 暂存 [名称]', topic='主持')
    app.router.register('暂存列表', listing, summary='查看本群暂存的团桌', topic='开团')
    app.router.register('取回', retrieve, summary='取回暂存团桌，准备后继续（原主持人或管理员）', usage='/团 取回 [序号或名称]', topic='主持')
