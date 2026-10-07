"""ENGINE03-001 generic custom-room plays: rule interpretation and proposals only.

A custom room (one started from a world brief rather than a fixed Story Pack)
may run any of the generic procedures below: investigation, testimony,
negotiation, relations, calendar, long projects, outfitting, conflict, chase,
debate, plans, flashbacks, oracle, transformation, private phases, regroup,
fortune and branch endings.  The Engine checks one requested action against the records
the platform already committed and proposes what would change.

The module is system-neutral and deterministic: no model call, no random
source, no clock, no state read and no state write.  It never decides who may
act and never rolls.  A proposal names the attribute check or the plain die the
platform must draw, and one list of operations for every possible result; the
platform checks permission, turn, CAS, audience and its own invariants, rolls
the original dice, picks the branch and commits the receipt.

Proposal ``se-custom-play-proposal/1.0.0``::

    check     None | {attribute_ref, difficulty}           d20 check, platform-rolled
    draw      None | {sides, bands: [{key, low, high, label}]}   plain die, platform-drawn
    outcomes  {'always' | 'success' | 'failure' | band key: [operation, ...]}

Operations::

    {'op': 'create', 'key', 'kind', 'audience': 'room' | 'members', 'members', 'state', 'document'}
    {'op': 'update', 'ref', 'revision', 'state', 'document'}
    {'op': 'resources', 'deltas': {resource_ref: int}}      the acting character
    {'op': 'complete_room'}                                  an ending concluded
    {'op': 'harm', 'joint_ref', 'resource_ref', 'amount', 'actor_refs'}
                                                             a lost joint danger wounds whoever failed
    {'op': 'advance_clock', 'joint_ref', 'clock_ref', 'delta': 1}
                                                             a lost joint danger moves its world clock
    {'op': 'use_skill', 'skill_ref'}                         the acting character spends one use of a
                                                             skill it learned, and the skill's own cost

机运盘 (fortune): before an important check the actor lays out up to four of the
twenty faces with a move; the platform rolls only after the layout is confirmed,
seals the original die and, when it lands on a laid-out face, gives the actor a
timed choice.  The Engine reads the actor's own modifiers from the platform's
``attribute_card`` and proposes one branch per face; the clock is the platform's.
"""
from __future__ import annotations

from copy import deepcopy

FEATURE = 'story.custom_plays/1.0.0'
CATALOG_METHOD = 'custom_play_catalog'
EVALUATE_METHOD = 'evaluate_custom_play'
CATALOG_SCHEMA = 'se-custom-play-catalog/1.0.0'
PROPOSAL_SCHEMA = 'se-custom-play-proposal/1.0.0'

SLOTS = ('清晨', '白天', '傍晚', '夜晚')
STANDING = ('敌对', '戒备', '冷淡', '中立', '友善', '信任', '盟友')
FLASHBACK_BUDGET = 2
OPEN_BRANCHES = 4
ORACLE_LIKELIHOOD = {'unlikely': 14, 'even': 11, 'likely': 8}
ORACLE_ANSWERS = (('no_and', '否，而且更糟'), ('no', '否'), ('no_but', '否，但有转机'),
                  ('yes_but', '是，但有代价'), ('yes', '是'), ('yes_and', '是，而且更好'))
FORTUNE_BANDS = (('misfortune', 1, 5, '厄运'), ('steady', 6, 15, '平稳'), ('boon', 16, 20, '好运'))
# 机运盘: a check's twenty faces read in five tiers; a laid-out move holds its fixed
# echo cost and spends it only when taken (孤注 takes every echo left).  Each chapter
# everyone starts again from the owner's echo setting; two wheels a chapter each.
WHEEL_TIERS = (('fumble', '大失败'), ('failure', '失败'), ('narrow', '险胜'), ('success', '成功'), ('critical', '大成功'))
WHEEL_MOVES = (('guard', '护住', 1), ('flip', '换面', 2), ('all_in', '孤注', 1))
WHEEL_ECHO, WHEEL_ECHO_MAX, WHEEL_FACES, WHEEL_PER_CHAPTER = 3, 6, 4, 2


class CustomPlayError(ValueError):
    """A rejected action; the message is a stable ``custom_play.*`` code."""


def _fail(code):
    raise CustomPlayError('custom_play.' + code)


# ---------------------------------------------------------------- input fields
# (name, type, label, option): text → maximum length, choice → options,
# int → (low, high), texts → maximum items, ref → record kind,
# attributes → maximum items (distinct attributes of the room's rules),
# layout → (maximum entries, moves): distinct faces 1–20, each with one move.
def _field(value, kind, option, rules, members):
    if kind == 'text':
        if not isinstance(value, str) or not value.strip() or len(value) > option:
            _fail('input_invalid')
        return value.strip()
    if kind == 'choice':
        if value not in option:
            _fail('input_invalid')
        return value
    if kind == 'int':
        if type(value) is not int or not option[0] <= value <= option[1]:
            _fail('input_invalid')
        return value
    if kind == 'texts':
        if not isinstance(value, list) or not 1 <= len(value) <= option:
            _fail('input_invalid')
        return [_field(item, 'text', 300, rules, members) for item in value]
    if kind == 'ref':
        if not isinstance(value, str) or not 1 <= len(value) <= 160:
            _fail('input_invalid')
        return value
    if kind == 'attribute':
        if not isinstance(value, str) or value not in rules['attributes']:
            _fail('attribute_invalid')
        return value
    if kind == 'attributes':
        if not isinstance(value, list) or not 1 <= len(value) <= option or len(set(map(str, value))) != len(value):
            _fail('attribute_invalid')
        return [_field(item, 'attribute', None, rules, members) for item in value]
    if kind == 'difficulty':
        if not isinstance(value, str) or value not in rules['difficulties']:
            _fail('difficulty_invalid')
        return value
    if kind == 'actor':
        if value not in members:
            _fail('actor_invalid')
        return value
    if kind == 'actors':
        if not isinstance(value, list) or not 1 <= len(value) <= len(members) or len(set(value)) != len(value):
            _fail('actor_invalid')
        return [_field(item, 'actor', None, rules, members) for item in value]
    raise AssertionError(kind)


CHECK = [('attribute_ref', 'attribute', '属性', None), ('difficulty', 'difficulty', '难度', None)]


class _Scope:
    """One evaluation: the actor, present members, visible records and rules."""

    def __init__(self, payload):
        self.actor = payload['actor_ref']
        self.members = list(payload['member_refs'])
        self.rules = payload['rules']
        self.records = payload['records']

    def all(self, kind, *states):
        return [item for item in self.records if item['kind'] == kind and (not states or item['state'] in states)]

    def get(self, ref, kind, *states):
        for item in self.records:
            if item['ref'] == ref and item['kind'] == kind:
                if states and item['state'] not in states:
                    _fail('state_invalid')
                return item
        _fail('record_missing')


def _create(key, kind, state, document, *, audience='room', members=()):
    return {'op': 'create', 'key': key, 'kind': kind, 'audience': audience, 'members': list(members),
            'state': state, 'document': document}


def _update(record, state, document):
    return {'op': 'update', 'ref': record['ref'], 'revision': record['revision'], 'state': state, 'document': document}


def _check(value):
    return {'attribute_ref': value['attribute_ref'], 'difficulty': value['difficulty']}


# ---------------------------------------------------------------- skills
# A skill is the platform's own reading of what the acting character learned
# (``skill_card``, members-only to that character): its uses left and whether its
# cost can still be paid.  The Engine never writes one; spending a use is the
# ``use_skill`` operation, which the platform applies to the character itself.
def _skill(s, ref):
    card = s.get(ref, 'skill_card')
    if card['document'].get('actor_ref') != s.actor:
        _fail('skill_not_yours')
    if card['state'] != 'ready':
        _fail('skill_spent')
    return card


def _use_skill(card):
    return {'op': 'use_skill', 'skill_ref': card['ref']}


# ------------------------------------------------------------- investigation
def _hypothesis_state(document):
    support, refute = len(document['support']), len(document['refute'])
    if support >= 2 and support > refute:
        return 'supported'
    if refute >= 2 and refute > support:
        return 'refuted'
    return 'contested' if support and refute else 'open'


def note_clue(s, v):
    document = {'title': v['title'], 'text': v['text'], 'source_kind': v['source_kind'], 'found_by': s.actor}
    return None, {'always': [_create('clue', 'clue', 'open', document)]}, '记录线索「%s」' % v['title']


def search(s, v):
    document = {'title': v['title'], 'text': v['text'], 'source_kind': 'evidence', 'found_by': s.actor}
    return _check(v), {'success': [_create('clue', 'clue', 'open', document)], 'failure': []}, '搜查「%s」' % v['title']


def propose_hypothesis(s, v):
    document = {'title': v['title'], 'text': v['text'], 'proposed_by': s.actor, 'support': [], 'refute': []}
    return None, {'always': [_create('hypothesis', 'hypothesis', 'open', document)]}, '提出假设「%s」' % v['title']


def weigh(s, v):
    record = s.get(v['hypothesis_ref'], 'hypothesis', 'open', 'contested', 'supported', 'refuted')
    s.get(v['clue_ref'], 'clue')
    document = deepcopy(record['document'])
    if any(item['clue_ref'] == v['clue_ref'] for item in document['support'] + document['refute']):
        _fail('already_linked')
    document['support' if v['stance'] == 'support' else 'refute'].append({'clue_ref': v['clue_ref'], 'actor_ref': s.actor})
    label = '支持' if v['stance'] == 'support' else '反驳'
    return None, {'always': [_update(record, _hypothesis_state(document), document)]}, '以线索%s假设「%s」' % (label, document['title'])


def conclude(s, v):
    need = 'supported' if v['verdict'] == 'accept' else 'refuted'
    record = s.get(v['hypothesis_ref'], 'hypothesis', need)
    document = {**record['document'], 'concluded_by': s.actor}
    state = 'accepted' if v['verdict'] == 'accept' else 'rejected'
    return None, {'always': [_update(record, state, document)]}, '%s假设「%s」' % ('采纳' if state == 'accepted' else '否定', document['title'])


def cite_fact(s, v):
    fact = s.get(v['fact_ref'], 'source_fact', 'confirmed')
    document = {**fact['document'], 'source_kind': 'author_world', 'source_ref': fact['ref'],
                'source_revision': fact['revision'], 'found_by': s.actor}
    return None, {'always': [_create('clue', 'clue', 'open', document)]}, '引用公开设定「%s」' % document['title']


def verify_hypothesis(s, v):
    record = s.get(v['hypothesis_ref'], 'hypothesis', 'open', 'supported', 'contested', 'accepted')
    fact = s.get(v['fact_ref'], 'source_fact', 'confirmed')
    # A matching authored assertion can be confirmed; semantic inference remains a hypothesis.
    matches = record['document']['text'].strip() == fact['document']['text'].strip()
    document = deepcopy(record['document'])
    document.setdefault('verifications', []).append({'actor_ref': s.actor, 'fact_ref': fact['ref'],
        'source_revision': fact['revision'], 'matched': matches})
    return None, {'always': [_update(record, 'confirmed' if matches else record['state'], document)]}, \
        '公开设定已确认该命题' if matches else '该设定不能直接确认命题，保留待核查'


def question_hypothesis(s, v):
    record = s.get(v['hypothesis_ref'], 'hypothesis', 'open', 'supported', 'contested', 'refuted', 'accepted')
    document = deepcopy(record['document'])
    document.setdefault('questions', []).append({'actor_ref': s.actor, 'text': v['question']})
    return None, {'always': [_update(record, record['state'], document)]}, '记录假设的待解问题'


def split_hypothesis(s, v):
    record = s.get(v['hypothesis_ref'], 'hypothesis')
    return None, {'always': [_create('hypothesis', 'hypothesis', 'open',
        {'title': v['title'], 'text': v['text'], 'parent_ref': record['ref'], 'parent_revision': record['revision'],
         'proposed_by': s.actor, 'support': [], 'refute': []})]}, '从原假设拆出新命题，证据需重新关联'


# 技能批注: a character reads one public fact through a skill it learned.  The note
# quotes the fact's own words (the sentence sharing the most character pairs with
# the skill and the reading), stays with its writer, and each character notes a
# fact once.
NOTE_EXCERPT = 160
_STOPS = frozenset('。！？；!?;\n')


def _pairs(text):
    return {text[i:i + 2] for i in range(len(text) - 1) if text[i].isalnum() and text[i + 1].isalnum()}


def _excerpt(text, probe):
    """The passage of ``text`` a reading leans on, and the character spans it shares with the reading."""
    sentences, start = [], 0
    for index, char in enumerate(text):
        if char in _STOPS:
            sentences.append(text[start:index + 1])
            start = index + 1
    sentences.append(text[start:])
    sentences = [item.strip() for item in sentences if item.strip()] or [text.strip()]
    wanted = _pairs(probe)

    def hits(passage):
        return sum(passage[i:i + 2] in wanted for i in range(len(passage) - 1))
    best = max(sentences, key=hits)  # the first of equals: deterministic
    if len(best) > NOTE_EXCERPT:
        best = max((best[i:i + NOTE_EXCERPT] for i in range(len(best) - NOTE_EXCERPT + 1)), key=hits)
    marks = []
    for i in range(len(best) - 1):
        if best[i:i + 2] in wanted:
            if marks and marks[-1][1] >= i:
                marks[-1][1] = i + 2
            else:
                marks.append([i, i + 2])
    return best, marks


def apply_skill(s, v):
    card = _skill(s, v['skill_ref'])
    fact = s.get(v['fact_ref'], 'source_fact', 'confirmed')
    if any(note['document']['fact_ref'] == fact['ref'] and note['document']['noted_by'] == s.actor for note in s.all('skill_note')):
        _fail('already_noted')
    skill = card['document']
    excerpt, marks = _excerpt(fact['document']['text'], skill['name'] + skill['text'] + v['reading'])
    document = {'title': fact['document']['title'], 'skill_ref': card['ref'], 'skill_id': skill['skill_id'],
                'skill_name': skill['name'], 'fact_ref': fact['ref'], 'fact_revision': fact['revision'],
                'reading': v['reading'], 'excerpt': excerpt, 'marks': marks, 'noted_by': s.actor}
    return None, {'always': [_create('note', 'skill_note', 'recorded', document, audience='members', members=[s.actor]),
                             _use_skill(card)]}, \
        '用「%s」批注「%s」，只本人可见' % (skill['name'], fact['document']['title'])


# ------------------------------------------------------------------ testimony
def record_testimony(s, v):
    document = {'speaker': v['speaker'], 'text': v['text'], 'recorded_by': s.actor, 'entries': []}
    return None, {'always': [_create('testimony', 'testimony', 'standing', document)]}, '记录%s的证词' % v['speaker']


def merge_hypotheses(s, v):
    left, right = s.get(v['left_ref'], 'hypothesis'), s.get(v['right_ref'], 'hypothesis')
    if left['ref'] == right['ref']:
        _fail('input_invalid')
    document = {'title': v['title'], 'text': v['text'], 'parents': [{'ref': r['ref'], 'revision': r['revision']} for r in (left, right)],
                'proposed_by': s.actor, 'support': [], 'refute': []}
    return None, {'always': [_create('hypothesis', 'hypothesis', 'open', document)]}, '合并为新的待核查命题，保留原假设并重新关联证据'


def withdraw_hypothesis(s, v):
    record = s.get(v['hypothesis_ref'], 'hypothesis', 'open', 'supported', 'refuted', 'contested', 'accepted', 'rejected')
    if record['document']['proposed_by'] != s.actor:
        _fail('not_proposer')
    return None, {'always': [_update(record, 'withdrawn', record['document'])]}, '本人撤回假设，保留证据与质询记录'


def _testimony_branch(record, entry, state):
    document = deepcopy(record['document'])
    document['entries'].append(entry)
    return [_update(record, 'contradicted' if record['state'] == 'contradicted' else state, document)]


def press(s, v):
    record = s.get(v['testimony_ref'], 'testimony', 'standing', 'shaken', 'contradicted')
    entry = {'kind': 'press', 'question': v['question'], 'actor_ref': s.actor}
    return _check(v), {'success': _testimony_branch(record, {**entry, 'outcome': 'yielded'}, 'shaken'),
                       'failure': _testimony_branch(record, {**entry, 'outcome': 'held'}, record['state'])}, \
        '追问%s的证词' % record['document']['speaker']


def present(s, v):
    record = s.get(v['testimony_ref'], 'testimony', 'standing', 'shaken', 'contradicted')
    clue = s.get(v['clue_ref'], 'clue')
    if clue['document']['source_kind'] not in {'evidence', 'observed', 'author_world'}:
        _fail('evidence_required')
    entry = {'kind': 'present', 'clue_ref': v['clue_ref'], 'claim': v['claim'], 'actor_ref': s.actor}
    return _check(v), {'success': _testimony_branch(record, {**entry, 'outcome': 'contradiction'}, 'contradicted'),
                       'failure': _testimony_branch(record, {**entry, 'outcome': 'dismissed'}, record['state'])}, \
        '向%s出示证据' % record['document']['speaker']


def annotate_testimony(s, v):
    """Append an attributed clarification/challenge; never overwrite a statement."""
    record = s.get(v['testimony_ref'], 'testimony', 'standing', 'shaken', 'contradicted')
    entry = {'kind': v['kind'], 'text': v['text'], 'actor_ref': s.actor,
             'statement_revision': record['revision']}
    return None, {'always': _testimony_branch(record, entry, record['state'])}, '补充%s的证词质询' % record['document']['speaker']


def compare_statement(s, v):
    record = s.get(v['testimony_ref'], 'testimony', 'standing', 'shaken', 'contradicted')
    other = s.get(v['other_testimony_ref'], 'testimony')
    if record['ref'] == other['ref']:
        _fail('input_invalid')
    entry = {'kind': 'compare', 'other_testimony_ref': other['ref'],
             'other_statement_revision': other['revision'], 'statement_revision': record['revision'],
             'text': v['text'], 'actor_ref': s.actor}
    return None, {'always': _testimony_branch(record, entry, record['state'])}, '对照两份原证词'


def withdraw_challenge(s, v):
    record = s.get(v['testimony_ref'], 'testimony', 'standing', 'shaken', 'contradicted')
    entries = record['document']['entries']
    index = v['entry'] - 1
    if index >= len(entries) or entries[index]['kind'] not in {'present', 'challenge_wording', 'compare'}:
        _fail('input_invalid')
    if entries[index]['actor_ref'] != s.actor:
        _fail('confirmation_not_yours')
    if any(e['kind'] == 'withdraw' and e['entry'] == v['entry'] for e in entries):
        _fail('state_invalid')
    entry = {'kind': 'withdraw', 'entry': v['entry'], 'text': v['reason'], 'actor_ref': s.actor}
    # Withdrawal records the speaker's change of position, not deletion of history.
    return None, {'always': _testimony_branch(record, entry, record['state'])}, '撤回本人质疑并保留原记录'


# ---------------------------------------------------------------- negotiation
NEGOTIATING = ('open', 'bargaining')


def open_talks(s, v):
    document = {'counterpart': v['counterpart'], 'topic': v['topic'], 'opened_by': s.actor, 'leverage': 0,
                'arguments': [], 'terms': []}
    return None, {'always': [_create('negotiation', 'negotiation', 'open', document)]}, '与%s展开交涉' % v['counterpart']


def argue_terms(s, v):
    record = s.get(v['negotiation_ref'], 'negotiation', *NEGOTIATING)

    def branch(delta, outcome):
        document = deepcopy(record['document'])
        document['leverage'] = max(-3, min(3, document['leverage'] + delta))
        document['arguments'].append({'actor_ref': s.actor, 'argument': v['argument'], 'outcome': outcome})
        return [_update(record, 'bargaining', document)]
    return _check(v), {'success': branch(1, 'gained'), 'failure': branch(-1, 'lost')}, \
        '在与%s的交涉中陈述理由' % record['document']['counterpart']


def propose_term(s, v):
    record = s.get(v['negotiation_ref'], 'negotiation', *NEGOTIATING)
    document = deepcopy(record['document'])
    if len(document['terms']) >= 8:
        _fail('limit_reached')
    document['terms'].append({'term_id': len(document['terms']) + 1, 'text': v['text'], 'proposed_by': s.actor, 'signatures': []})
    return None, {'always': [_update(record, record['state'], document)]}, '提出条款'


def sign_term(s, v):
    record = s.get(v['negotiation_ref'], 'negotiation', *NEGOTIATING)
    document = deepcopy(record['document'])
    term = next((item for item in document['terms'] if item['term_id'] == v['term_id']), None)
    if term is None:
        _fail('record_missing')
    if any(item['actor_ref'] == s.actor for item in term['signatures']):
        _fail('already_signed')
    term['signatures'].append({'actor_ref': s.actor})
    return None, {'always': [_update(record, record['state'], document)]}, '本人签署第%d条' % v['term_id']


def settle_talks(s, v):
    record = s.get(v['negotiation_ref'], 'negotiation', *NEGOTIATING)
    document = deepcopy(record['document'])
    signed = [item['term_id'] for item in document['terms'] if item['signatures']]
    if document['leverage'] < 1:
        _fail('leverage_insufficient')
    if not signed:
        _fail('terms_unsigned')
    document['agreed_terms'] = signed
    document['obligations'] = [{'term_id': item['term_id'],
        'signers': [entry['actor_ref'] for entry in item['signatures']], 'updates': []}
        for item in document['terms'] if item['term_id'] in signed]
    return None, {'always': [_update(record, 'agreed', document)]}, '与%s达成协议' % document['counterpart']


def contract_context(s, v):
    record = s.get(v['negotiation_ref'], 'negotiation', *NEGOTIATING)
    document = deepcopy(record['document'])
    document.setdefault('conditions', []).append({'actor_ref': s.actor, 'kind': v['kind'], 'text': v['text']})
    return None, {'always': [_update(record, record['state'], document)]}, '记录本人交涉条件'


def amend_term(s, v):
    record = s.get(v['negotiation_ref'], 'negotiation', *NEGOTIATING)
    document = deepcopy(record['document'])
    term = next((t for t in document['terms'] if t['term_id'] == v['term_id']), None)
    if term is None:
        _fail('record_missing')
    if len(document['terms']) >= 8:
        _fail('limit_reached')
    document['terms'].append({'term_id': len(document['terms']) + 1, 'text': v['text'],
        'proposed_by': s.actor, 'signatures': [], 'alternative_to': v['term_id']})
    return None, {'always': [_update(record, record['state'], document)]}, '提出替代条款，原条款及签名保留'


def obligation_update(s, v):
    record = s.get(v['negotiation_ref'], 'negotiation', 'agreed')
    document = deepcopy(record['document'])
    obligation = next((o for o in document.get('obligations', []) if o['term_id'] == v['term_id']), None)
    if obligation is None:
        _fail('record_missing')
    if s.actor not in obligation['signers']:
        _fail('confirmation_not_yours')
    if any(e['actor_ref'] == s.actor for e in obligation['updates']):
        _fail('state_invalid')
    obligation['updates'].append({'actor_ref': s.actor, 'status': v['status'], 'text': v['text']})
    return None, {'always': [_update(record, record['state'], document)]}, '记录本人履约结果'


def open_deliberation(s, v):
    document = {'title': v['title'], 'brief': v['brief'], 'options': v['options'], 'risk': v['risk'],
        'impact': v['impact'], 'delay': v['delay'], 'checkpoint': v['checkpoint'], 'members': s.members,
        'opened_by': s.actor, 'questions': [], 'votes': [], 'rounds': [], 'reviews': []}
    return None, {'always': [_create('deliberation', 'deliberation', 'questioning', document)]}, '公开议程与后果，等待质询和本人表态'


def question_policy(s, v):
    record = s.get(v['deliberation_ref'], 'deliberation', 'questioning', 'voting')
    document = deepcopy(record['document'])
    document['questions'].append({'actor_ref': s.actor, 'text': v['text']})
    return None, {'always': [_update(record, record['state'], document)]}, '记录政策质询'


def vote_policy(s, v):
    record = s.get(v['deliberation_ref'], 'deliberation', 'questioning', 'voting')
    document = deepcopy(record['document'])
    if s.actor not in document['members'] or v['option'] > len(document['options']):
        _fail('input_invalid')
    if any(e['actor_ref'] == s.actor for e in document['votes']):
        _fail('already_voted')
    document['votes'].append({'actor_ref': s.actor, 'option': v['option']})
    state = 'voting'
    if len(document['votes']) == len(document['members']):
        counts = [sum(e['option'] == i + 1 for e in document['votes']) for i in range(len(document['options']))]
        winners = [i + 1 for i, count in enumerate(counts) if count == max(counts)]
        if len(winners) == 1:
            state = 'decided'
            calendar = _calendar(s)
            document.update(selected=winners[0], due=(_now(calendar['document']) if calendar else 0) + document['delay'])
        else:
            state = 'tied'
    return None, {'always': [_update(record, state, document)]}, '提交本人政策表态，按冻结成员计票'


def revise_policy(s, v):
    record = s.get(v['deliberation_ref'], 'deliberation', 'questioning', 'voting', 'tied')
    if record['document']['opened_by'] != s.actor:
        _fail('not_proposer')
    document = deepcopy(record['document'])
    document['rounds'].append({'options': document['options'], 'votes': document['votes']})
    document['options'], document['votes'] = v['options'], []
    return None, {'always': [_update(record, 'questioning', document)]}, '保留原表态，修订方案后重新表决'


def implement_policy(s, v):
    record = s.get(v['deliberation_ref'], 'deliberation', 'decided')
    if record['document']['opened_by'] != s.actor:
        _fail('not_proposer')
    calendar = _calendar(s)
    if (_now(calendar['document']) if calendar else 0) < record['document']['due']:
        _fail('deadline_not_reached')
    return None, {'always': [_update(record, 'implemented', {**record['document'], 'implemented_by': s.actor})]}, \
        '公布议定方案；具体资产和角色变化仍走各自正式操作'


def review_policy(s, v):
    record = s.get(v['deliberation_ref'], 'deliberation', 'implemented')
    document = deepcopy(record['document'])
    document['reviews'].append({'actor_ref': s.actor, 'text': v['text']})
    return None, {'always': [_update(record, record['state'], document)]}, '记录实施复查与世界反应'


def withdraw_policy(s, v):
    record = s.get(v['deliberation_ref'], 'deliberation', 'questioning', 'voting', 'tied', 'decided')
    if record['document']['opened_by'] != s.actor:
        _fail('not_proposer')
    return None, {'always': [_update(record, 'withdrawn', record['document'])]}, '撤回议案并保留全部表态'


def walk_away(s, v):
    record = s.get(v['negotiation_ref'], 'negotiation', *NEGOTIATING)
    return None, {'always': [_update(record, 'broken_off', record['document'])]}, '中止与%s的交涉' % record['document']['counterpart']


# ------------------------------------------------------------------ relations
def _relation(s, subject, kind):
    return next((item for item in s.all('relation') if item['document']['subject'] == subject
                 and item['document']['subject_kind'] == kind), None)


def _relation_op(s, v, change, text):
    record = _relation(s, v['subject'], v['subject_kind'])
    document = deepcopy(record['document']) if record else {'subject': v['subject'], 'subject_kind': v['subject_kind'],
                                                            'standing': 0, 'memories': []}
    document['standing'] = max(-3, min(3, document['standing'] + change))
    document['tier'] = STANDING[document['standing'] + 3]
    document['memories'].append({'actor_ref': s.actor, 'text': text, 'change': change})
    return _update(record, 'active', document) if record else _create('relation', 'relation', 'active', document)


def appeal(s, v):
    return _check(v), {'success': [_relation_op(s, v, 1, v['approach'])], 'failure': [_relation_op(s, v, -1, v['approach'])]}, \
        '争取%s的态度' % v['subject']


def remember(s, v):
    return None, {'always': [_relation_op(s, v, 0, v['text'])]}, '记下与%s的往来' % v['subject']


def remember_dimension(s, v):
    cause = s.get(v['clue_ref'], 'clue')
    op = _relation_op(s, v, 0, v['text'])
    document = op['document']
    document['memories'][-1].update(cause_ref=cause['ref'], cause_revision=cause['revision'], dimension=v['dimension'])
    stances = document.setdefault('stances', [])
    stance = next((e for e in stances if e['actor_ref'] == s.actor and e['dimension'] == v['dimension']), None)
    if stance:
        stance['value'] = max(-3, min(3, stance['value'] + v['change']))
    else:
        stances.append({'actor_ref': s.actor, 'dimension': v['dimension'], 'value': v['change']})
    return None, {'always': [op]}, '以原线索记录本人关系记忆，不代替他人感情'


def set_goal(s, v):
    document = {'companion': v['companion'], 'goal': v['goal'], 'set_by': s.actor}
    return None, {'always': [_create('goal', 'companion_goal', 'active', document)]}, '确立%s的同伴目标' % v['companion']


def resolve_goal(s, v):
    record = s.get(v['goal_ref'], 'companion_goal', 'active')
    return None, {'always': [_update(record, v['result'], {**record['document'], 'resolved_by': s.actor})]}, \
        '同伴目标%s' % ('达成' if v['result'] == 'fulfilled' else '放弃')


def companion_agenda(s, v):
    record = s.get(v['goal_ref'], 'companion_goal', 'active')
    document = deepcopy(record['document'])
    document.setdefault('agenda', []).append({'actor_ref': s.actor, 'kind': v['kind'], 'text': v['text']})
    return None, {'always': [_update(record, record['state'], document)]}, '补充同伴议程，建议不代替玩家行动'


def publish_reputation(s, v):
    cause = s.get(v['clue_ref'], 'clue')
    document = {'title': v['subject'], 'audience_name': v['audience_name'], 'text': v['text'],
        'source_ref': cause['ref'], 'source_revision': cause['revision'], 'source_kind': cause['document']['source_kind'],
        'published_by': s.actor, 'route': v['route'], 'corrections': []}
    return None, {'always': [_create('reputation', 'reputation', 'published', document)]}, '向%s传播关于%s的有来源说法' % (v['audience_name'], v['subject'])


def correct_reputation(s, v):
    record = s.get(v['reputation_ref'], 'reputation', 'published', 'contested')
    cause = s.get(v['clue_ref'], 'clue')
    document = deepcopy(record['document'])
    document['corrections'].append({'actor_ref': s.actor, 'source_ref': cause['ref'],
        'source_revision': cause['revision'], 'text': v['text']})
    return None, {'always': [_update(record, 'contested', document)]}, '公开纠错并保留原传播与来源'


# ------------------------------------------------------------------- calendar
def _now(document):
    return (document['day'] - 1) * len(SLOTS) + document['slot']


def _calendar(s):
    found = s.all('calendar')
    return found[0] if found else None


def _advance(s, slots, activity):
    """Operations moving the room calendar forward by ``slots``, never back."""
    record = _calendar(s)
    document = deepcopy(record['document']) if record else {'day': 1, 'slot': 0, 'log': []}
    before = _now(document)
    after = before + slots
    document['day'], document['slot'] = after // len(SLOTS) + 1, after % len(SLOTS)
    document['log'] = (document['log'] + [{'actor_ref': s.actor, 'activity': activity, 'slots': slots,
                                           'from': before, 'to': after}])[-50:]
    ops = [_update(record, 'running', document) if record else _create('calendar', 'calendar', 'running', document)]
    for item in s.all('appointment', 'scheduled', 'arrived', 'invited') + s.all('deadline', 'pending'):
        at = (item['document']['day'] - 1) * len(SLOTS) + item['document']['slot']
        if item['kind'] == 'appointment' and at <= after:
            state = 'expired' if item['state'] == 'invited' else 'missed' if at < after else 'arrived'
            ops.append(_update(item, state, item['document']))
        elif item['kind'] == 'deadline' and at < after:
            ops.append(_update(item, 'expired', item['document']))
    return ops


def _future(s, v):
    record = _calendar(s)
    now = _now(record['document']) if record else 0
    if (v['day'] - 1) * len(SLOTS) + v['slot'] <= now:
        _fail('time_past')
    return {'title': v['title'], 'day': v['day'], 'slot': v['slot'], 'set_by': s.actor}


def schedule(s, v):
    _calendar_capacity(s)
    _reserve_activity(s, v, [s.actor], 1)
    return None, {'always': [_create('appointment', 'appointment', 'scheduled', _future(s, v))]}, \
        '预约「%s」：第%d天%s' % (v['title'], v['day'], SLOTS[v['slot']])


def set_deadline(s, v):
    _calendar_capacity(s)
    return None, {'always': [_create('deadline', 'deadline', 'pending', _future(s, v))]}, \
        '设定期限「%s」：第%d天%s' % (v['title'], v['day'], SLOTS[v['slot']])


def meet_deadline(s, v):
    record = s.get(v['deadline_ref'], 'deadline', 'pending')
    return None, {'always': [_update(record, 'met', {**record['document'], 'met_by': s.actor})]}, '按期完成「%s」' % record['document']['title']


def spend_time(s, v):
    return None, {'always': _advance(s, v['slots'], v['activity'])}, '%s，用去%d个时段' % (v['activity'], v['slots'])


def _calendar_capacity(s):
    if len(s.all('appointment', 'scheduled', 'invited')) + len(s.all('deadline', 'pending')) >= 12:
        _fail('limit_reached')


def _reserve_activity(s, v, members, slots, exclude=None):
    start = _now(v)
    window = next((r for r in s.all('location_window') if r['document']['location'] == v.get('location')), None)
    if window and not window['document']['opens'] <= v['slot'] < v['slot'] + slots <= window['document']['closes']:
        _fail('location_closed')
    for item in s.all('appointment', 'scheduled', 'invited'):
        doc = item['document']
        if item['ref'] != exclude and set(members) & set(doc.get('members', [doc['set_by']])) \
                and start < _now(doc) + doc.get('slots', 1) and _now(doc) < start + slots:
            _fail('schedule_conflict')
    for item in s.all('availability', 'active'):
        doc = item['document']
        if doc['actor_ref'] in members and doc['availability'] == 'unavailable' \
                and start < _now(doc) + doc['slots'] and _now(doc) < start + slots:
            _fail('schedule_conflict')


def invite_activity(s, v):
    _calendar_capacity(s)
    if s.actor not in v['member_actor_refs']:
        _fail('not_member')
    document = _future(s, v)
    _reserve_activity(s, v, v['member_actor_refs'], v['slots'])
    document.update(members=v['member_actor_refs'], slots=v['slots'], location=v['location'],
        confirmations=[{'actor_ref': s.actor, 'response': 'accept'}], history=[])
    state = 'scheduled' if len(document['members']) == 1 else 'invited'
    return None, {'always': [_create('appointment', 'appointment', state, document)]}, '发出预约邀请，全部本人接受后才生效'


def respond_activity(s, v):
    record = s.get(v['appointment_ref'], 'appointment', 'invited')
    document = deepcopy(record['document'])
    if s.actor not in document['members']:
        _fail('not_member')
    if any(e['actor_ref'] == s.actor for e in document['confirmations']):
        _fail('already_signed')
    _future(s, document)
    document['confirmations'].append({'actor_ref': s.actor, 'response': v['response']})
    state = 'cancelled' if v['response'] == 'decline' else 'scheduled' if len(document['confirmations']) == len(document['members']) else 'invited'
    return None, {'always': [_update(record, state, document)]}, '提交本人预约回应'


def reschedule_activity(s, v):
    record = s.get(v['appointment_ref'], 'appointment', 'invited', 'scheduled')
    document = deepcopy(record['document'])
    if document['set_by'] != s.actor:
        _fail('not_proposer')
    _future(s, {**document, **v})
    _reserve_activity(s, {**document, **v}, document.get('members', [s.actor]), document.get('slots', 1), record['ref'])
    document.setdefault('history', []).append({'day': document['day'], 'slot': document['slot'], 'confirmations': document.get('confirmations', [])})
    document.update(day=v['day'], slot=v['slot'])
    if 'members' in document:
        document['confirmations'] = [{'actor_ref': s.actor, 'response': 'accept'}]
    return None, {'always': [_update(record, 'invited' if len(document.get('members', [])) > 1 else 'scheduled', document)]}, '改期后重新取得参与者同意'


def cancel_activity(s, v):
    record = s.get(v['appointment_ref'], 'appointment', 'invited', 'scheduled', 'arrived')
    if record['document']['set_by'] != s.actor:
        _fail('not_proposer')
    return None, {'always': [_update(record, 'cancelled', record['document'])]}, '取消预约并释放时段，原记录保留'


def attend_activity(s, v):
    record = s.get(v['appointment_ref'], 'appointment', 'scheduled', 'arrived')
    document = record['document']
    if s.actor not in document.get('members', [document['set_by']]):
        _fail('not_member')
    calendar = _calendar(s)
    now = _now(calendar['document']) if calendar else 0
    if now != _now(document):
        _fail('appointment_not_due')
    operations = [op for op in _advance(s, document.get('slots', 1), document['title']) if op.get('ref') != record['ref']]
    operations.append(_update(record, 'completed', {**document, 'completed_by': s.actor}))
    return None, {'always': operations}, '完成已确认活动并结算原时段成本'


def declare_availability(s, v):
    _future(s, {**v, 'title': '可用时段'})
    document = {**v, 'actor_ref': s.actor}
    return None, {'always': [_create('availability', 'availability', 'active', document)]}, '声明本人可用时段，已有预约需另行取消'


def clear_availability(s, v):
    record = s.get(v['availability_ref'], 'availability', 'active')
    if record['document']['actor_ref'] != s.actor:
        _fail('confirmation_not_yours')
    return None, {'always': [_update(record, 'closed', record['document'])]}, '撤回本人时段声明'


def configure_location(s, v):
    if v['opens'] >= v['closes']:
        _fail('input_invalid')
    document = {**v, 'set_by': s.actor}
    old = next((r for r in s.all('location_window') if r['document']['location'] == v['location']), None)
    operation = _update(old, 'active', document) if old else _create('location', 'location_window', 'active', document)
    return None, {'always': [operation]}, '房主设定地点日常开放时段'


# ------------------------------------------------------------------- projects
def start_project(s, v):
    document = {'title': v['title'], 'project_kind': v['project_kind'], 'segments': v['segments'], 'progress': 0,
                'owner_ref': s.actor, 'log': []}
    return None, {'always': [_create('project', 'project', 'active', document)]}, '开始%s「%s」' % (
        '训练' if v['project_kind'] == 'training' else '长期项目', v['title'])


def work_project(s, v):
    record = s.get(v['project_ref'], 'project', 'active')
    title = record['document']['title']

    def branch(gain, outcome):
        document = deepcopy(record['document'])
        gain = min(gain, document['segments'] - document['progress'])
        document['progress'] += gain
        document['log'].append({'actor_ref': s.actor, 'gain': gain, 'outcome': outcome})
        for milestone in document.get('milestones', []):
            if document['progress'] >= milestone['threshold']:
                milestone['status'] = 'reached'
        state = 'complete' if document['progress'] >= document['segments'] else 'active'
        return [_update(record, state, document)] + _advance(s, 1, '推进「%s」' % title)
    return _check(v), {'success': branch(2, 'success'), 'failure': branch(0, 'failure')}, '推进「%s」' % title


def set_milestone(s, v):
    record = s.get(v['project_ref'], 'project', 'active')
    document = deepcopy(record['document'])
    if document['owner_ref'] != s.actor:
        _fail('not_proposer')
    if document['progress'] or v['threshold'] > document['segments']:
        _fail('state_invalid')
    milestones = document.setdefault('milestones', [])
    if len(milestones) >= document['segments'] or any(m['threshold'] == v['threshold'] for m in milestones):
        _fail('limit_reached')
    milestones.append({'threshold': v['threshold'], 'text': v['text'], 'status': 'pending'})
    return None, {'always': [_update(record, record['state'], document)]}, '在投入前冻结项目里程碑'


def attempt_finish(s, v):
    record = s.get(v['project_ref'], 'project', 'active')
    if record['document']['progress'] * 2 < record['document']['segments']:
        _fail('progress_insufficient')
    def branch(won):
        document = deepcopy(record['document'])
        before = document['progress']
        document['progress'] = document['segments'] if won else max(0, before - 1)
        document['log'].append({'actor_ref': s.actor, 'gain': document['progress'] - before,
            'outcome': 'success' if won else 'failure', 'activity': '提前结算'})
        if won:
            for milestone in document.get('milestones', []):
                milestone['status'] = 'reached'
        return [_update(record, 'complete' if won else 'active', document)] + _advance(s, 1, '提前结算「%s」' % document['title'])
    return _check(v), {'success': branch(True), 'failure': branch(False)}, '提前结算：耗时一个时段，失败损失一格进度'


def claim_training(s, v):
    record = s.get(v['project_ref'], 'project', 'complete')
    if record['document']['owner_ref'] != s.actor or record['document']['project_kind'] != 'training':
        _fail('confirmation_not_yours')
    return None, {'always': [_update(record, 'claimed', {**record['document'], 'claimed_by': s.actor, 'attribute_ref': v['attribute_ref']}),
        {'op': 'advance_attribute', 'attribute_ref': v['attribute_ref'], 'delta': 1, 'cause_ref': record['ref']}]}, \
        '本人领取训练成果：所选属性增加一点，不超过本房属性上限'


def rest(s, v):
    recovery = s.rules.get('recovery', {}).get('rest')
    if not recovery:
        _fail('rest_unavailable')
    deltas = dict(recovery['cost'])
    for ref, amount in recovery['effect'].items():
        deltas[ref] = deltas.get(ref, 0) + amount
    return None, {'always': [{'op': 'resources', 'deltas': deltas}] + _advance(s, 1, '休整')}, '休整一个时段'


# ------------------------------------------------- conflict / chase / debate
CONTESTS = {'playConflict': 'conflict', 'playChase': 'chase', 'playDebate': 'debate'}


def _contest(key, v, s, document):
    base = {'procedure': key, 'opened_by': s.actor, 'ours': 0, 'theirs': 0, 'exchanges': [],
            'participants': [s.actor], 'withdrawals': [], 'advantages': []}
    return None, {'always': [_create('contest', 'contest', 'engaged', {**base, **document})]}


def open_conflict(s, v):
    check, outcomes = _contest('conflict', v, s, {'opponent': v['opponent'], 'stakes': v['stakes'], 'length': v['length']})
    return check, outcomes, '与%s展开冲突' % v['opponent']


def open_chase(s, v):
    check, outcomes = _contest('chase', v, s, {'quarry': v['quarry'], 'role': v['role'], 'distance': v['distance'],
                                                'gap': v['distance']})
    return check, outcomes, ('追赶%s' if v['role'] == 'pursue' else '摆脱%s') % v['quarry']


def open_debate(s, v):
    check, outcomes = _contest('debate', v, s, {'topic': v['topic'], 'stance': v['stance'], 'rounds': v['rounds']})
    return check, outcomes, '就「%s」展开辩论' % v['topic']


def _contest_result(document, won, magnitude=1):
    procedure = document['procedure']
    if won:
        document['ours'] += magnitude
    else:
        document['theirs'] += magnitude
    if procedure == 'conflict':
        if document['ours'] >= document['length']:
            return 'won'
        return 'lost' if document['theirs'] >= document['length'] else 'engaged'
    if procedure == 'chase':
        closer = won == (document['role'] == 'pursue')
        document['gap'] += -magnitude if closer else magnitude
        if document['gap'] <= 0:
            return 'won' if document['role'] == 'pursue' else 'lost'
        if document['gap'] >= document['distance'] * 2:
            return 'lost' if document['role'] == 'pursue' else 'won'
        return 'engaged'
    if len(document['exchanges']) < document['rounds']:
        return 'engaged'
    return 'won' if document['ours'] > document['theirs'] else 'lost' if document['ours'] < document['theirs'] else 'drawn'


def exchange(s, v, play):
    record = s.get(v['contest_ref'], 'contest', 'engaged')
    if record['document']['procedure'] != CONTESTS[play]:
        _fail('procedure_mismatch')
    if any(e['actor_ref'] == s.actor for e in record['document'].get('withdrawals', [])):
        _fail('not_member')
    if not v.get('_argument') and any(d['document']['owner_ref'] == s.actor and d['document']['contest_ref'] == record['ref'] for d in s.all('argument_deck', 'active')):
        _fail('argument_deck_required')

    def branch(won):
        document = deepcopy(record['document'])
        if s.actor not in document.setdefault('participants', [document['opened_by']]):
            document['participants'].append(s.actor)
        document['exchanges'].append({'actor_ref': s.actor, 'text': v['text'], 'outcome': 'success' if won else 'failure'})
        return [_update(record, _contest_result(document, won), document)]
    return _check(v), {'success': branch(True), 'failure': branch(False)}, '推进%s' % {
        'conflict': '冲突', 'chase': '追逐', 'debate': '辩论'}[CONTESTS[play]]


def concede(s, v, play):
    record = s.get(v['contest_ref'], 'contest', 'engaged')
    if record['document']['procedure'] != CONTESTS[play]:
        _fail('procedure_mismatch')
    document = deepcopy(record['document'])
    participants = document.get('participants', [document['opened_by']])
    if s.actor not in participants or any(e['actor_ref'] == s.actor for e in document.get('withdrawals', [])):
        _fail('not_member')
    document.setdefault('withdrawals', []).append({'actor_ref': s.actor})
    complete = {e['actor_ref'] for e in document['withdrawals']} == set(participants)
    if complete:
        document['conceded_by'] = s.actor
    operations = [_update(record, 'conceded' if complete else 'engaged', document)]
    operations += [_update(deck, 'closed', deck['document']) for deck in s.all('argument_deck', 'active')
        if deck['document']['owner_ref'] == s.actor and deck['document']['contest_ref'] == record['ref']]
    return None, {'always': operations}, '本人退出；全部参与者退出后才整体收尾'


def join_contest(s, v, play):
    record = s.get(v['contest_ref'], 'contest', 'engaged')
    if record['document']['procedure'] != CONTESTS[play]:
        _fail('procedure_mismatch')
    document = deepcopy(record['document'])
    participants = document.setdefault('participants', [document['opened_by']])
    if s.actor in participants:
        _fail('already_signed')
    participants.append(s.actor)
    return None, {'always': [_update(record, record['state'], document)]}, '本人加入当前对抗程序'


def prepare_position(s, v, play):
    check, outcomes, _ = exchange(s, v, play)
    record = s.get(v['contest_ref'], 'contest')
    if any(e['actor_ref'] == s.actor and e['available'] for e in record['document'].get('advantages', [])):
        _fail('limit_reached')
    document = deepcopy(record['document'])
    if s.actor not in document.setdefault('participants', [document['opened_by']]):
        document['participants'].append(s.actor)
    document.setdefault('advantages', []).append({'actor_ref': s.actor, 'text': v['text'], 'available': True})
    document['exchanges'].append({'actor_ref': s.actor, 'text': v['text'], 'outcome': 'prepared'})
    outcomes['success'] = [_update(record, _contest_result(document, True, 0), document)]
    return check, outcomes, '争取有利位置：成功取得一次受控行动，失败推进对手'


def maneuver(s, v, play):
    check, outcomes, _ = exchange(s, v, play)
    record = s.get(v['contest_ref'], 'contest')
    if v['position'] == 'controlled' and not any(e['actor_ref'] == s.actor and e['available'] for e in record['document'].get('advantages', [])):
        _fail('preparation_required')
    for result, won in (('success', True), ('failure', False)):
        document = deepcopy(record['document'])
        if s.actor not in document.setdefault('participants', [document['opened_by']]):
            document['participants'].append(s.actor)
        if v['position'] == 'controlled':
            next(e for e in document['advantages'] if e['actor_ref'] == s.actor and e['available'])['available'] = False
        effect = 'great' if v['position'] == 'desperate' else 'limited' if v['position'] == 'controlled' else 'standard'
        magnitude = 2 if effect == 'great' else 0 if not won and effect == 'limited' else 1
        document['exchanges'].append({'actor_ref': s.actor, 'text': v['text'], 'outcome': result, 'position': v['position'], 'effect': effect})
        outcomes[result] = [_update(record, _contest_result(document, won, magnitude), document)]
    return check, outcomes, '受控消耗原准备且失败不推进对手；绝境成功／失败各推进两格'


ARGUMENTS = ('facts', 'empathy', 'interests', 'authority', 'threat', 'concession', 'redirect', 'contradiction')


def prepare_arguments(s, v):
    contest = s.get(v['contest_ref'], 'contest', 'engaged')
    if contest['document']['procedure'] != 'debate':
        _fail('procedure_mismatch')
    if any(e['actor_ref'] == s.actor for e in contest['document'].get('withdrawals', [])):
        _fail('not_member')
    if any(r['document']['owner_ref'] == s.actor and r['document']['contest_ref'] == contest['ref'] for r in s.all('argument_deck')):
        _fail('already_signed')
    document = {'title': '本人论据动作库', 'contest_ref': contest['ref'], 'owner_ref': s.actor,
        'hand': list(ARGUMENTS[:3]), 'draw_pile': list(ARGUMENTS[3:]), 'discard': [], 'exhaust': [], 'points': 3, 'log': []}
    return None, {'always': [_create('arguments', 'argument_deck', 'active', document, audience='members', members=[s.actor])]}, '启用本场论据动作库，每次论证消耗一张手牌和一点行动额度'


def refresh_arguments(s, v):
    record = s.get(v['deck_ref'], 'argument_deck', 'active')
    document = deepcopy(record['document'])
    if document['owner_ref'] != s.actor:
        _fail('not_owner')
    s.get(document['contest_ref'], 'contest', 'engaged')
    if document['points'] != 0:
        _fail('state_invalid')
    pile = document['draw_pile'] + document['discard']
    document.update(hand=pile[:3], draw_pile=pile[3:], discard=[], points=len(pile[:3]))
    return None, {'always': [_update(record, 'active', document)]}, '按公开规则顺序补充论据，耗竭的方法不回到手牌'


def play_argument(s, v):
    deck = s.get(v['deck_ref'], 'argument_deck', 'active')
    if deck['document']['owner_ref'] != s.actor:
        _fail('not_owner')
    if deck['document']['points'] < 1 or v['method'] not in deck['document']['hand']:
        _fail('argument_unavailable')
    clue = s.get(v['clue_ref'], 'clue')
    if v['method'] in {'facts', 'authority', 'contradiction'} and clue['document']['source_kind'] == 'speaker_claim':
        _fail('evidence_required')
    value = {**v, 'contest_ref': deck['document']['contest_ref'], '_argument': True}
    check, outcomes, _ = exchange(s, value, 'playDebate')
    record = s.get(value['contest_ref'], 'contest')
    for result, won in (('success', True), ('failure', False)):
        document = deepcopy(record['document'])
        if s.actor not in document.setdefault('participants', [document['opened_by']]):
            document['participants'].append(s.actor)
        document['exchanges'].append({'actor_ref': s.actor, 'text': v['text'], 'outcome': result,
            'argument_method': v['method'], 'clue_ref': clue['ref'], 'clue_revision': clue['revision']})
        magnitude = 2 if v['method'] in {'threat', 'contradiction'} else 0 if not won and v['method'] in {'empathy', 'concession'} else 1
        state = _contest_result(document, won, magnitude)
        cards = deepcopy(deck['document'])
        cards['hand'].remove(v['method'])
        cards['points'] -= 1
        cards['exhaust' if v['method'] == 'threat' else 'discard'].append(v['method'])
        cards['log'].append({'actor_ref': s.actor, 'method': v['method'], 'outcome': result})
        outcomes[result] = [_update(record, state, document), _update(deck, 'active' if state == 'engaged' else 'closed', cards)]
    return check, outcomes, '论据行动：消耗本人原手牌和额度，平台保留原骰'


# --------------------------------------------------------------- joint danger
# 合力险关: one danger held on two fronts, the original two-front rule
# (JOINT_POLICY).  Everyone claims one front and makes one roll of their own, on
# their own turn; a front holds when at least half of its people succeed and the
# danger is cleared only when both fronts hold.  The first roll closes the roster.
# Only those whose own roll failed are hurt, and only when the danger is lost;
# settling early counts nobody's missing roll as a success, and hurts nobody for it.
# The seats still free must be able to cover every front nobody holds yet.
JOINT_POLICY = 'group.two-fronts-half-success/1.0.0'
JOINT_FRONTS = ('a', 'b')
JOINT_OPEN = ('forming', 'holding')


def _joint_harm(s):
    """The resource the room's own failure cost wounds, if the rules name one."""
    harm = (s.rules.get('failure_costs') or {}).get('harm') or {}
    return next(iter(harm)) if len(harm) == 1 else None


def _joint_outcome(document, clock_moved):
    rolled = {e['actor_ref']: e['outcome'] for e in document['rolls']}
    fronts = []
    for front in document['fronts']:
        members = [e['actor_ref'] for e in document['roster'] if e['front'] == front['key']]
        successes = sum(rolled.get(ref) == 'success' for ref in members)
        required = (len(members) + 1) // 2
        fronts.append({'front': front['key'], 'count': len(members), 'required': required,
                       'successes': successes, 'held': bool(members) and successes >= required})
    cleared = all(item['held'] for item in fronts)
    return {'policy': JOINT_POLICY, 'cleared': cleared, 'fronts': fronts,
            'injured': [] if cleared else sorted(ref for ref, outcome in rolled.items() if outcome == 'failure'),
            'absent': sorted(e['actor_ref'] for e in document['roster'] if e['actor_ref'] not in rolled),
            'clock_moved': not cleared and clock_moved}


def _joint_settle(s, joint, document):
    clock = next((item for item in s.all('world_clock', 'running') if item['ref'] == document['clock_ref']), None)
    result = document['result'] = _joint_outcome(document, clock is not None)
    operations = [_update(joint, 'cleared' if result['cleared'] else 'overrun', document)]
    if result['cleared']:
        operations.append(_create('fact', 'clue', 'open', {'title': document['title'], 'text': document['fact'],
            'source_kind': 'observed', 'found_by': s.actor, 'joint_ref': joint['ref']}))
        return operations
    if document['harm'] and result['injured']:
        operations.append({'op': 'harm', 'joint_ref': joint['ref'], 'resource_ref': document['harm_resource'],
                           'amount': document['harm'], 'actor_refs': result['injured']})
    if result['clock_moved']:
        operations.append({'op': 'advance_clock', 'joint_ref': joint['ref'], 'clock_ref': clock['ref'], 'delta': 1})
    return operations


def form_joint(s, v):
    if s.all('joint', *JOINT_OPEN):
        _fail('joint_active')
    if v['front_a'] == v['front_b']:
        _fail('input_invalid')
    resource = _joint_harm(s)
    if v['harm'] and resource is None:
        _fail('harm_unavailable')
    clock = v.get('clock_ref') or None
    if clock is not None and not isinstance(clock, str):
        _fail('input_invalid')
    record = s.get(clock, 'world_clock', 'running') if clock else None
    if not v['harm'] and record is None:
        _fail('cost_required')
    document = {'title': v['title'], 'text': v['text'], 'difficulty': v['difficulty'],
                'fronts': [{'key': 'a', 'label': v['front_a'], 'attributes': v['attributes_a']},
                           {'key': 'b', 'label': v['front_b'], 'attributes': v['attributes_b']}],
                'size': v['size'], 'harm': v['harm'], 'harm_resource': resource if v['harm'] else None,
                'clock_ref': clock, 'clock_title': record['document']['title'] if record else None,
                'fact': v['fact'], 'policy': JOINT_POLICY, 'formed_by': s.actor,
                'roster': [{'actor_ref': s.actor, 'front': v['front']}], 'rolls': [], 'result': None}
    return None, {'always': [_create('joint', 'joint', 'forming', document)]}, \
        '立下险关「%s」：%s／%s' % (v['title'], v['front_a'], v['front_b'])


def join_joint(s, v):
    joint = s.get(v['joint_ref'], 'joint', 'forming')
    document = deepcopy(joint['document'])
    if any(e['actor_ref'] == s.actor for e in document['roster']):
        _fail('already_joined')
    if len(document['roster']) >= document['size']:
        _fail('joint_full')
    # A seat on a held front may not take the place an empty front still needs, or nobody could ever roll.
    unheld = set(JOINT_FRONTS) - {e['front'] for e in document['roster']}
    if v['front'] not in unheld and document['size'] - len(document['roster']) <= len(unheld):
        _fail('front_needed')
    document['roster'].append({'actor_ref': s.actor, 'front': v['front']})
    label = next(item['label'] for item in document['fronts'] if item['key'] == v['front'])
    return None, {'always': [_update(joint, 'forming', document)]}, '认领「%s」，一起守「%s」' % (label, document['title'])


def roll_joint(s, v):
    joint = s.get(v['joint_ref'], 'joint', *JOINT_OPEN)
    base = joint['document']
    seat = next((e for e in base['roster'] if e['actor_ref'] == s.actor), None)
    if seat is None:
        _fail('not_joined')
    if any(e['actor_ref'] == s.actor for e in base['rolls']):
        _fail('already_rolled')
    if {e['front'] for e in base['roster']} != set(JOINT_FRONTS):
        _fail('front_empty')
    front = next(item for item in base['fronts'] if item['key'] == seat['front'])
    if v['attribute_ref'] not in front['attributes']:
        _fail('attribute_off_front')

    def branch(outcome):
        document = deepcopy(base)
        document['rolls'].append({'actor_ref': s.actor, 'front': seat['front'], 'attribute_ref': v['attribute_ref'],
                                  'text': v['text'], 'outcome': outcome})
        if len(document['rolls']) == len(document['roster']):
            return _joint_settle(s, joint, document)
        return [_update(joint, 'holding', document)]
    return ({'attribute_ref': v['attribute_ref'], 'difficulty': base['difficulty']},
            {'success': branch('success'), 'failure': branch('failure')}, '守住「%s」：%s' % (front['label'], base['title']))


def settle_joint(s, v):
    joint = s.get(v['joint_ref'], 'joint', *JOINT_OPEN)
    document = deepcopy(joint['document'])
    # The one who set the danger closes it; if they have left the table, anyone holding a front may.
    if document['formed_by'] != s.actor and (document['formed_by'] in s.members
                                             or all(e['actor_ref'] != s.actor for e in document['roster'])):
        _fail('not_initiator')
    if not document['rolls']:
        return None, {'always': [_update(joint, 'withdrawn', document)]}, '撤下险关「%s」' % document['title']
    return None, {'always': _joint_settle(s, joint, document)}, '提前收尾险关「%s」：没掷骰的人不计成功' % document['title']


# ---------------------------------------------------------------------- plans
def draft_plan(s, v):
    document = {'title': v['title'], 'goal': v['goal'], 'drafted_by': s.actor,
                'steps': [{'text': text, 'actor_ref': None, 'status': 'open'} for text in v['steps']], 'withdrawals': [],
                'extraction': {'route': '按来路撤回；实际移动仍须提交行动', 'risk': '退出不退回已付成本，未完成目标不算完成'}}
    return None, {'always': [_create('plan', 'plan', 'draft', document)]}, '拟定计划「%s」' % v['title']


def _step(record, index):
    if not 1 <= index <= len(record['document']['steps']):
        _fail('record_missing')
    return index - 1


def claim_step(s, v):
    record = s.get(v['plan_ref'], 'plan', 'draft')
    index = _step(record, v['step'])
    document = deepcopy(record['document'])
    if any(e['actor_ref'] == s.actor for e in document.get('withdrawals', [])):
        _fail('not_member')
    if document['steps'][index]['actor_ref'] is not None:
        _fail('already_claimed')
    document['steps'][index]['actor_ref'] = s.actor
    return None, {'always': [_update(record, 'draft', document)]}, '认领计划第%d步' % v['step']


def confirm_plan(s, v):
    record = s.get(v['plan_ref'], 'plan', 'draft')
    if any(step['actor_ref'] is None for step in record['document']['steps']):
        _fail('steps_unclaimed')
    if s.actor not in {record['document']['drafted_by'], *(step['actor_ref'] for step in record['document']['steps'])}:
        _fail('not_member')
    return None, {'always': [_update(record, 'confirmed', {**record['document'], 'confirmed_by': s.actor})]}, \
        '确认计划「%s」' % record['document']['title']


def execute_step(s, v):
    record = s.get(v['plan_ref'], 'plan', 'confirmed', 'underway', 'compromised')
    index = _step(record, v['step'])
    step = record['document']['steps'][index]
    if step['actor_ref'] != s.actor:
        _fail('step_not_yours')
    if step['status'] != 'open':
        _fail('state_invalid')

    def branch(status):
        document = deepcopy(record['document'])
        document['steps'][index]['status'] = status
        if document['steps'][index].get('preparation'):
            document['steps'][index]['preparation']['used'] = True
        if document['steps'][index].get('complication'):
            document['steps'][index]['complication']['used'] = True
        statuses = [item['status'] for item in document['steps']]
        state = 'completed' if all(item == 'done' for item in statuses) else 'partial' if 'open' not in statuses else \
            'compromised' if statuses.count('failed') >= 2 else 'underway'
        return [_update(record, state, document)]
    check = _check(v)
    shift = -int(bool(step.get('preparation') and not step['preparation']['used'])) + int(bool(step.get('complication') and not step['complication']['used']))
    tiers = sorted(s.rules['difficulties'], key=s.rules['difficulties'].get)
    check['difficulty'] = tiers[max(0, min(len(tiers) - 1, tiers.index(check['difficulty']) + shift))]
    return check, {'success': branch('done'), 'failure': branch('failed')}, '执行计划第%d步' % v['step']


def evacuate(s, v):
    record = s.get(v['plan_ref'], 'plan', 'draft', 'confirmed', 'underway', 'compromised', 'partial')
    document = deepcopy(record['document'])
    participants = {document['drafted_by'], *(step['actor_ref'] for step in document['steps'] if step['actor_ref'])}
    if s.actor not in participants or any(e['actor_ref'] == s.actor for e in document.get('withdrawals', [])):
        _fail('not_member')
    document.setdefault('withdrawals', []).append({'actor_ref': s.actor})
    for step in document['steps']:
        if step['actor_ref'] == s.actor and step['status'] == 'open':
            step['status'] = 'withdrawn'
    state = 'evacuated' if {e['actor_ref'] for e in document['withdrawals']} == participants else record['state']
    return None, {'always': [_update(record, state, document)]}, '本人退出计划；原成本和他人的行动保留'


def set_extraction(s, v):
    record = s.get(v['plan_ref'], 'plan', 'draft')
    if record['document']['drafted_by'] != s.actor:
        _fail('not_proposer')
    if any(step['actor_ref'] is not None for step in record['document']['steps']):
        _fail('state_invalid')
    return None, {'always': [_update(record, 'draft', {**record['document'], 'extraction': {'route': v['route'], 'risk': v['risk']}})]}, '在认领前冻结撤离路线和风险'


def revise_plan(s, v):
    original = s.get(v['plan_ref'], 'plan')
    if s.actor not in {original['document']['drafted_by'], *(step['actor_ref'] for step in original['document']['steps'])}:
        _fail('not_member')
    _, outcomes, _ = draft_plan(s, v)
    outcomes['always'][0]['document'].update(parent_ref=original['ref'], parent_revision=original['revision'])
    return None, outcomes, '另拟方案并重新认领；原计划、承诺和原骰保留'


def create_advantage(s, v):
    source = s.get(v['clue_ref'], 'clue')
    if source['document'].get('source_kind') not in {'observed', 'evidence', 'author_world'}:
        _fail('evidence_required')
    document = {'title': v['title'], 'text': v['text'], 'aspect_kind': v['aspect_kind'], 'source_ref': source['ref'],
        'source_revision': source['revision'], 'created_by': s.actor, 'beneficiary_ref': v['target_actor_ref'], 'charges': 1}
    return _check(v), {'success': [_create('aspect', 'aspect', 'active', document)], 'failure': []}, '创造有来源的有限优势，成功后仅由指定角色本人调用一次'


def invoke_aspect(s, v):
    aspect = s.get(v['aspect_ref'], 'aspect', 'active')
    if aspect['document']['beneficiary_ref'] != s.actor:
        _fail('confirmation_not_yours')
    plan = s.get(v['plan_ref'], 'plan', 'confirmed', 'underway', 'compromised')
    document = deepcopy(plan['document'])
    step = document['steps'][_step(plan, v['step'])]
    if step['actor_ref'] != s.actor or step['status'] != 'open':
        _fail('step_not_yours')
    if step.get('preparation') and not step['preparation']['used']:
        _fail('preparation_exists')
    if aspect['document'].get('compel_ref') and step.get('complication', {}).get('source_ref') == aspect['document']['compel_ref']:
        _fail('same_complication')
    step['preparation'] = {'source_ref': aspect['ref'], 'text': aspect['document']['title'], 'used': False}
    return None, {'always': [_update(aspect, 'spent', {**aspect['document'], 'charges': 0, 'used_by': s.actor}),
        _update(plan, plan['state'], document)]}, '本人使用原优势，下一次该步骤检定降低一级难度'


def clear_aspect(s, v):
    aspect = s.get(v['aspect_ref'], 'aspect', 'active')
    if aspect['document']['beneficiary_ref'] != s.actor:
        _fail('confirmation_not_yours')
    return None, {'always': [_update(aspect, 'closed', aspect['document'])]}, '本人放弃未使用的优势'


def offer_compel(s, v):
    aspect = s.get(v['aspect_ref'], 'aspect', 'active')
    plan = s.get(v['plan_ref'], 'plan', 'confirmed', 'underway', 'compromised')
    step = plan['document']['steps'][_step(plan, v['step'])]
    if step['actor_ref'] != v['target_actor_ref'] or step['status'] != 'open':
        _fail('step_not_yours')
    document = {'title': v['title'], 'text': v['text'], 'aspect_ref': aspect['ref'], 'plan_ref': plan['ref'],
        'plan_revision': plan['revision'], 'step': v['step'], 'target_actor_ref': v['target_actor_ref'],
        'offered_by': s.actor, 'refusal_cost': 0, 'reward_charges': 1, 'responses': []}
    return None, {'always': [_create('compel', 'compel', 'awaiting_target', document)]}, '提出额外困难：本人可拒绝且不扣费，接受才影响待执行步骤'


def answer_compel(s, v):
    record = s.get(v['compel_ref'], 'compel', 'awaiting_target')
    document = deepcopy(record['document'])
    if document['target_actor_ref'] != s.actor:
        _fail('confirmation_not_yours')
    document['responses'].append({'actor_ref': s.actor, 'decision': v['decision']})
    if v['decision'] == 'reject':
        return None, {'always': [_update(record, 'declined', document)]}, '本人拒绝额外困难，没有扣费或更改计划'
    s.get(document['aspect_ref'], 'aspect', 'active')
    plan = s.get(document['plan_ref'], 'plan', 'confirmed', 'underway', 'compromised')
    if plan['revision'] != document['plan_revision']:
        _fail('state_invalid')
    plan_document = deepcopy(plan['document'])
    step = plan_document['steps'][_step(plan, document['step'])]
    if step['actor_ref'] != s.actor or step['status'] != 'open' or step.get('complication'):
        _fail('step_not_yours')
    step['complication'] = {'source_ref': record['ref'], 'text': document['text'], 'used': False}
    reward = {'title': '接受困难的补偿准备', 'text': document['text'], 'aspect_kind': 'advantage',
        'source_ref': record['ref'], 'source_revision': record['revision'], 'compel_ref': record['ref'],
        'created_by': s.actor, 'beneficiary_ref': s.actor, 'charges': 1}
    return None, {'always': [_update(record, 'accepted', document), _update(plan, plan['state'], plan_document),
        _create('compensation', 'aspect', 'active', reward)]}, '本人接受：此步骤提高一级难度，获得一次不能抵消本次困难的后续准备'


# 援手契印: a character offers a learned skill to stand by named companions —
# protecting them, or opening a negotiation on terms each of them writes for
# themselves (what we want, the red line, the way out).  Every companion answers
# in person and one refusal voids the seal; once all agree the offerer seals it on
# their own turn, spending one use of the skill and its cost.  A seal adds no dice:
# it is a standing state on the table until the offerer or a companion releases it.
SUPPORT_KINDS = ('protect', 'negotiate')
SUPPORT_PENDING = ('awaiting_consent', 'awaiting_seal')
SUPPORT_LIMIT = 6
TERMS = ('want', 'red_line', 'exit')


def _terms(v, needed):
    given = [name for name in TERMS if v.get(name) is not None]
    if not needed:
        if given:
            _fail('input_invalid')
        return None
    if len(given) != len(TERMS):
        _fail('terms_required')
    return {name: _field(v[name], 'text', 200, None, None) for name in TERMS}


def offer_support(s, v):
    card = _skill(s, v['skill_ref'])
    companions = v['companion_actor_refs']
    if s.actor in companions:
        _fail('actor_invalid')
    if any(r['document']['offered_by'] == s.actor for r in s.all('support', *SUPPORT_PENDING)):
        _fail('support_pending')
    if len(s.all('support', 'sealed', *SUPPORT_PENDING)) >= SUPPORT_LIMIT:
        _fail('limit_reached')
    terms = _terms(v, v['support_kind'] == 'negotiate')
    skill = card['document']
    document = {'title': skill['name'], 'skill_ref': card['ref'], 'skill_id': skill['skill_id'], 'skill_text': skill['text'],
                'support_kind': v['support_kind'], 'text': v['text'], 'offered_by': s.actor, 'companions': companions,
                'terms': {'actor_ref': s.actor, **terms} if terms else None, 'responses': []}
    kind = '护住' if v['support_kind'] == 'protect' else '协商'
    return None, {'always': [_create('support', 'support', 'awaiting_consent', document)]}, \
        '以「%s」发起援手契印（%s），等同伴本人答复' % (skill['name'], kind)


def answer_support(s, v):
    record = s.get(v['support_ref'], 'support', 'awaiting_consent')
    document = deepcopy(record['document'])
    if s.actor not in document['companions']:
        _fail('not_companion')
    if any(entry['actor_ref'] == s.actor for entry in document['responses']):
        _fail('already_answered')
    agree = v['decision'] == 'agree'
    terms = _terms(v, agree and document['support_kind'] == 'negotiate')
    document['responses'].append({'actor_ref': s.actor, 'decision': v['decision'], **({'terms': terms} if terms else {})})
    if not agree:
        return None, {'always': [_update(record, 'declined', document)]}, '本人婉拒「%s」契印，契印作废' % document['title']
    agreed = {entry['actor_ref'] for entry in document['responses'] if entry['decision'] == 'agree'} == set(document['companions'])
    return None, {'always': [_update(record, 'awaiting_seal' if agreed else 'awaiting_consent', document)]}, \
        '本人同意「%s」契印%s' % (document['title'], '；同伴都已同意，等发起人落印' if agreed else '')


def seal_support(s, v):
    record = s.get(v['support_ref'], 'support', 'awaiting_seal')
    if record['document']['offered_by'] != s.actor:
        _fail('not_offerer')
    if any(ref not in s.members for ref in record['document']['companions']):
        _fail('companion_absent')
    card = _skill(s, record['document']['skill_ref'])
    return None, {'always': [_update(record, 'sealed', record['document']), _use_skill(card)]}, \
        '「%s」契印落下，用去一次技能' % record['document']['title']


def end_support(s, v):
    record = s.get(v['support_ref'], 'support', 'sealed', *SUPPORT_PENDING)
    document = deepcopy(record['document'])
    if record['state'] != 'sealed':
        if document['offered_by'] != s.actor:
            _fail('not_proposer')
        return None, {'always': [_update(record, 'withdrawn', document)]}, '撤回「%s」契印，尚未落印，技能没有用去' % document['title']
    if s.actor not in {document['offered_by'], *document['companions']}:
        _fail('not_party')
    document['released_by'] = s.actor
    return None, {'always': [_update(record, 'released', document)]}, '解除「%s」契印，已用去的技能不退' % document['title']


# ------------------------------------------------------------------ flashback
def flashback(s, v):
    used = [item for item in s.all('flashback') if item['document']['actor_ref'] == s.actor]
    if len(used) >= FLASHBACK_BUDGET:
        _fail('budget_spent')
    document = {'title': v['title'], 'preparation': v['preparation'], 'actor_ref': s.actor, 'rewrites_history': False,
                'effect_scope': 'future_plan_step', 'history_sources': [r['ref'] for r in s.records if r['kind'] in {'source_fact', 'source_event'}]}
    return _check(v), {'success': [_create('flashback', 'flashback', 'awaiting_review', document)],
                       'failure': [_create('flashback', 'flashback', 'failed', document)]}, '闪回准备「%s」' % v['title']


def review_flashback(s, v):
    record = s.get(v['flashback_ref'], 'flashback', 'awaiting_review')
    review = {'flashback_ref': record['ref'], 'reviewed_by': s.actor, 'decision': v['decision'], 'reason': v['reason'],
        'history_sources': [r['ref'] for r in s.records if r['kind'] in {'source_fact', 'source_event'}]}
    return None, {'always': [_update(record, 'established' if v['decision'] == 'approve' else 'rejected', record['document']),
        _create('review', 'flashback_review', 'recorded', review)]}, '核对当前原历史；批准仅提供一次未来行动准备'


def use_flashback(s, v):
    record = s.get(v['flashback_ref'], 'flashback', 'established')
    if record['document']['actor_ref'] != s.actor:
        _fail('not_owner')
    plan = s.get(v['plan_ref'], 'plan', 'confirmed', 'underway', 'compromised')
    document = deepcopy(plan['document'])
    step = document['steps'][_step(plan, v['step'])]
    if step['actor_ref'] != s.actor or step['status'] != 'open':
        _fail('step_not_yours')
    if step.get('preparation') and not step['preparation']['used']:
        _fail('preparation_exists')
    step['preparation'] = {'source_ref': record['ref'], 'text': record['document']['title'], 'used': False}
    return None, {'always': [_update(record, 'spent', record['document']), _update(plan, plan['state'], document)]}, '原闪回用于本人待执行步骤，难度降低一级，使用后消耗'


# --------------------------------------------------------------------- oracle
def _oracle_bands(threshold):
    edges = ((1, threshold - 8), (threshold - 7, threshold - 3), (threshold - 2, threshold - 1),
             (threshold, threshold + 1), (threshold + 2, threshold + 5), (threshold + 6, 20))
    bands = []
    for (key, label), (low, high) in zip(ORACLE_ANSWERS, edges):
        low, high = max(1, low), min(20, high)
        if low <= high:
            bands.append({'key': key, 'low': low, 'high': high, 'label': label})
    return bands


def ask_oracle(s, v):
    bands = _oracle_bands(ORACLE_LIKELIHOOD[v['likelihood']])
    outcomes = {band['key']: [_create('oracle', 'oracle', 'suggestion', {
        'question': v['question'], 'likelihood': v['likelihood'], 'answer': band['key'], 'answer_label': band['label'],
        'asked_by': s.actor, 'establishes_fact': False})] for band in bands}
    return {'sides': 20, 'bands': bands}, outcomes, '询问神谕：%s' % v['question']


ORACLE_TABLES = {
    'action': ('追寻', '守护', '交换', '揭示'), 'theme': ('信任', '责任', '失落', '希望'),
    'location': ('熟悉地点', '被忽略的入口', '边界地带', '临时避难处'),
    'complication': ('时间紧迫', '消息矛盾', '资源短缺', '出现新的选择'),
}


def configure_oracle(s, v):
    old = next((r for r in s.all('oracle_table') if r['document']['category'] == v['category']), None)
    document = {'category': v['category'], 'entries': v['entries'], 'set_by': s.actor}
    operation = _update(old, 'active', document) if old else _create('oracle-table', 'oracle_table', 'active', document)
    return None, {'always': [operation]}, '房主保存本房神谕建议表'


def consult_oracle(s, v):
    table = next((r for r in s.all('oracle_table') if r['document']['category'] == v['category']), None)
    entries = table['document']['entries'] if table else ORACLE_TABLES[v['category']]
    bands = [{'key': 'entry_' + str(i + 1), 'low': i * 20 // len(entries) + 1,
              'high': (i + 1) * 20 // len(entries), 'label': text} for i, text in enumerate(entries)]
    outcomes = {b['key']: [_create('oracle', 'oracle', 'suggestion', {'question': v['question'], 'category': v['category'],
        'answer': b['key'], 'answer_label': b['label'], 'table_source': table['ref'] if table else 'engine.default',
        'table_revision': table['revision'] if table else 1, 'asked_by': s.actor, 'establishes_fact': False})] for b in bands}
    return {'sides': 20, 'bands': bands}, outcomes, '抽取本房神谕建议；不会直接建立事实或消耗建议中的资源'


# ------------------------------------------------------------- transformation
def propose_change(s, v):
    heir = v.get('heir_actor_ref')
    if v['change_kind'] == 'legacy':
        if heir is None or heir == v['target_actor_ref']:
            _fail('heir_required')
        _field(heir, 'actor', None, s.rules, s.members)
    elif heir is not None:
        _fail('input_invalid')
    document = {'title': v['title'], 'change': v['change'], 'change_kind': v['change_kind'],
                'target_actor_ref': v['target_actor_ref'], 'heir_actor_ref': heir, 'proposed_by': s.actor,
                'confirmations': []}
    return None, {'always': [_create('transformation', 'transformation', 'awaiting_target', document)]}, \
        '提出%s「%s」' % ('传承' if v['change_kind'] == 'legacy' else '转变', v['title'])


def confirm_change(s, v):
    record = s.get(v['transformation_ref'], 'transformation', 'awaiting_target', 'awaiting_heir')
    document = deepcopy(record['document'])
    role = 'target' if record['state'] == 'awaiting_target' else 'heir'
    if s.actor != document[role + '_actor_ref']:
        _fail('confirmation_not_yours')
    document['confirmations'].append({'actor_ref': s.actor, 'role': role})
    state = 'awaiting_heir' if role == 'target' and document['change_kind'] == 'legacy' else 'confirmed'
    return None, {'always': [_update(record, state, document)]}, '本人确认「%s」' % document['title']


def decline_change(s, v):
    record = s.get(v['transformation_ref'], 'transformation', 'awaiting_target', 'awaiting_heir')
    role = 'target' if record['state'] == 'awaiting_target' else 'heir'
    if s.actor != record['document'][role + '_actor_ref']:
        _fail('confirmation_not_yours')
    return None, {'always': [_update(record, 'declined', {**record['document'], 'declined_by': s.actor})]}, \
        '本人拒绝「%s」' % record['document']['title']


def withdraw_change(s, v):
    record = s.get(v['transformation_ref'], 'transformation', 'awaiting_target', 'awaiting_heir')
    if s.actor != record['document']['proposed_by']:
        _fail('not_proposer')
    return None, {'always': [_update(record, 'withdrawn', record['document'])]}, '撤回「%s」' % record['document']['title']


# Host advice never changes difficulty, resources, turns or a player's intent.
def assess_pressure(s, v):
    context = s.all('host_context')[0] if s.all('host_context') else None
    if not context:
        _fail('record_missing')
    active = [r for r in s.records if r['kind'] == 'contest' and r['state'] == 'engaged' or r['kind'] == 'plan' and r['state'] == 'compromised']
    density = len(active)
    failures = context['document']['failure_streak']
    blocked = density >= v['ceiling'] or failures >= 3
    document = {'title': '主持节奏建议', 'assessed_by': s.actor, 'ceiling': v['ceiling'], 'active_pressure': density,
        'failure_streak': failures, 'block_new_pressure': blocked, 'recommendation': '恢复或开放线索机会' if blocked else '可邀请新的探索机会',
        'sources': [{'ref': r['ref'], 'revision': r['revision']} for r in active], 'context_revision': context['revision'],
        'effect': '仅建议；不自动增加难度、扣资源或制造危机'}
    return None, {'always': [_create('pressure', 'pressure_advice', 'suggestion', document, audience='members', members=[s.actor])]}, '核对当前公开压力，生成主持可见建议'


def request_spotlight(s, v):
    return None, {'always': [_create('request', 'spotlight_request', 'pending', {'text': v['text'], 'requested_by': s.actor})]}, '本人请求一次选择机会'


def defer_spotlight(s, v):
    request = s.get(v['request_ref'], 'spotlight_request', 'pending')
    if request['document']['requested_by'] != s.actor:
        _fail('not_owner')
    return None, {'always': [_update(request, 'withdrawn', request['document'])]}, '本人暂缓选择机会请求'


def recommend_spotlight(s, v):
    context = s.all('host_context')[0] if s.all('host_context') else None
    if not context:
        _fail('record_missing')
    counts = context['document']['opportunity_counts']
    requested = {r['document']['requested_by'] for r in s.all('spotlight_request', 'pending')}
    target = min(s.members, key=lambda actor: (actor not in requested, counts.get(actor, 0), s.members.index(actor)))
    document = {'title': '选择机会建议', 'recommended_by': s.actor, 'target_actor_ref': target,
        'opportunity_counts': counts, 'pending_requests': sorted(requested), 'context_revision': context['revision'],
        'effect': '只建议邀请；本人仍可拒绝，不自动执行行动或决定感情'}
    return None, {'always': [_create('spotlight', 'spotlight_advice', 'suggestion', document, audience='members', members=[s.actor])]}, '根据近期公开行动和本人请求建议邀请对象'


def invite_spotlight(s, v):
    return None, {'always': [_create('invitation', 'spotlight_invitation', 'pending', {'text': v['text'],
        'target_actor_ref': v['target_actor_ref'], 'invited_by': s.actor})]}, '邀请同桌作出自己的选择'


def respond_spotlight(s, v):
    invitation = s.get(v['invitation_ref'], 'spotlight_invitation', 'pending')
    if invitation['document']['target_actor_ref'] != s.actor:
        _fail('confirmation_not_yours')
    document = {**invitation['document'], 'response': {'actor_ref': s.actor, 'decision': v['decision']}}
    return None, {'always': [_update(invitation, 'accepted' if v['decision'] == 'accept' else 'declined', document)]}, '本人回应邀请；行动仍须另行声明'


# ------------------------------------------------ private phases and regroup
def _phase(s, ref, *states):
    record = s.get(ref, 'private_phase', *states)
    if s.actor not in record['document']['members']:
        _fail('not_member')
    return record


def open_phase(s, v):
    if s.actor not in v['member_actor_refs']:
        _fail('not_member')
    document = {'title': v['title'], 'members': v['member_actor_refs'], 'opened_by': s.actor, 'ready': [], 'withdrawals': []}
    return None, {'always': [_create('phase', 'private_phase', 'open', document, audience='members',
                                     members=v['member_actor_refs'])]}, '开启私人阶段'


def phase_note(s, v):
    record = _phase(s, v['phase_ref'], 'open', 'regrouping')
    if any(e['actor_ref'] == s.actor for e in record['document'].get('withdrawals', [])):
        _fail('not_member')
    document = {'phase_ref': record['ref'], 'text': v['text'], 'actor_ref': s.actor}
    return None, {'always': [_create('note', 'private_note', 'recorded', document, audience='members',
                                     members=record['document']['members'])]}, '记录私人阶段进展'


def phase_check(s, v):
    record = _phase(s, v['phase_ref'], 'open')
    if any(e['actor_ref'] == s.actor for e in record['document'].get('withdrawals', [])):
        _fail('not_member')
    used = sum(r['document']['phase_ref'] == record['ref'] and r['document']['actor_ref'] == s.actor for r in s.all('private_check'))
    if used >= 3:
        _fail('phase_budget_spent')
    document = {'phase_ref': record['ref'], 'text': v['text'], 'actor_ref': s.actor, 'spent': used + 1, 'budget': 3}
    return _check(v), {result: [_create('check', 'private_check', 'recorded', {**document, 'outcome': result},
        audience='members', members=record['document']['members'])] for result in ('success', 'failure')}, '私人阶段检定；成功或失败均消耗一次本阶段额度'


def close_phase(s, v):
    record = _phase(s, v['phase_ref'], 'open', 'regrouping')
    document = deepcopy(record['document'])
    if any(e['actor_ref'] == s.actor for e in document.get('withdrawals', [])):
        _fail('not_member')
    document.setdefault('withdrawals', []).append({'actor_ref': s.actor})
    document['ready'] = [e for e in document['ready'] if e['actor_ref'] != s.actor]
    closed = {e['actor_ref'] for e in document['withdrawals']} == set(document['members'])
    return None, {'always': [_update(record, 'closed' if closed else record['state'], document)]}, '本人退出私人阶段，原记录保留'


def ready_to_regroup(s, v):
    record = _phase(s, v['phase_ref'], 'open', 'regrouping')
    document = deepcopy(record['document'])
    if any(e['actor_ref'] == s.actor for e in document.get('withdrawals', [])):
        _fail('not_member')
    if any(item['actor_ref'] == s.actor for item in document['ready']):
        _fail('already_ready')
    document['ready'].append({'actor_ref': s.actor, 'share': v['share']})
    return None, {'always': [_update(record, 'regrouping', document)]}, '准备汇合'


def regroup(s, v):
    record = _phase(s, v['phase_ref'], 'regrouping')
    document = record['document']
    if {item['actor_ref'] for item in document['ready']} | {e['actor_ref'] for e in document.get('withdrawals', [])} != set(document['members']):
        _fail('members_not_ready')
    shared = {item['actor_ref'] for item in document['ready']}
    if s.actor not in shared:
        _fail('not_member')
    public = {'phase_ref': record['ref'], 'members': [ref for ref in document['members'] if ref in shared], 'shares': document['ready'],
              'regrouped_by': s.actor}
    return None, {'always': [_update(record, 'regrouped', document), _create('regroup', 'regroup', 'public', public)]}, \
        '私人阶段汇合'


# -------------------------------------------------------------------- fortune
def draw_fortune(s, v):
    bands = [{'key': key, 'low': low, 'high': high, 'label': label} for key, low, high, label in FORTUNE_BANDS]
    outcomes = {band['key']: [_create('fortune', 'fortune', 'frozen', {
        'stake': v['stake'], 'tier': band['key'], 'tier_label': band['label'], 'drawn_by': s.actor})] for band in bands}
    return {'sides': 20, 'bands': bands}, outcomes, '判定机运：%s' % v['stake']


def settle_fortune(s, v):
    record = s.get(v['fortune_ref'], 'fortune', 'frozen')
    if record['document']['drawn_by'] != s.actor:
        _fail('not_owner')
    return None, {'always': [_update(record, 'settled', {**record['document'], 'settlement': v['use']})]}, '机运收尾'


# 机运盘: a check laid out before the roll.  The plan stays with the actor until the
# roll; the platform's die picks one face's branch and the result is public.
_TIER_LABELS = dict(WHEEL_TIERS)
_TIER_RANK = {key: index for index, (key, _) in enumerate(WHEEL_TIERS)}
_MOVES = {key: (label, cost) for key, label, cost in WHEEL_MOVES}


def wheel_tier(face, modifier, dc):
    """One face of a d20 check in the wheel's five tiers: natural 1 and 20 first, then the margin."""
    if face == 1:
        return 'fumble'
    if face == 20:
        return 'critical'
    margin = face + modifier - dc
    return ('fumble' if margin <= -10 else 'failure' if margin < 0 else 'narrow' if margin < 5
            else 'success' if margin < 10 else 'critical')


def wheel_move(move, face, faces):
    """(final face, final tier) when ``move`` is taken on ``face``, or None where it cannot help.

    护住 lifts a face on the failing side to 险胜; 孤注 turns 险胜 or 成功 into 大成功;
    换面 turns the die over to its opposite face (the two always add up to 21), and is
    laid out only where the other side reads better."""
    tier = faces[face - 1]
    if move == 'guard':
        return (face, 'narrow') if tier in ('fumble', 'failure') else None
    if move == 'all_in':
        return (face, 'critical') if tier in ('narrow', 'success') else None
    if move == 'flip':
        other = 21 - face
        return (other, faces[other - 1]) if _TIER_RANK[faces[other - 1]] > _TIER_RANK[tier] else None
    return None


def _wheel_card(s):
    """The actor's own modifiers, as the platform lays them for that character alone."""
    found = [item for item in s.all('attribute_card') if item['document'].get('actor_ref') == s.actor]
    if len(found) != 1:
        _fail('record_missing')
    return found[0]['document']['modifiers']


def _wheels(s):
    return [item for item in s.all('fortune') if item['document'].get('drawn_by') == s.actor and item['document'].get('wheel')]


def _wheel_echo(s, chapter):
    """Echo left to the actor this chapter: the owner's setting less what the actor's wheels spent in it."""
    setting = s.all('fortune_echo')
    start = min(WHEEL_ECHO_MAX, setting[0]['document']['echo'] if setting else WHEEL_ECHO)
    return max(0, start - sum(item['document']['wheel']['spent'] for item in _wheels(s) if item['document']['wheel']['chapter'] == chapter))


def _wheel_open(s, chapter):
    """A new wheel waits for none of one's own to be chosen, and fits this chapter's two."""
    if any(item['state'] == 'choosing' for item in _wheels(s)):
        _fail('fortune_pending')
    if sum(item['document']['wheel']['chapter'] == chapter for item in _wheels(s)) >= WHEEL_PER_CHAPTER:
        _fail('wheel_quota')


def _wheel_layout(raw, faces):
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > WHEEL_FACES:
        _fail('input_invalid')
    layout = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {'face', 'move'} or type(item['face']) is not int \
                or not 1 <= item['face'] <= 20 or item['move'] not in _MOVES:
            _fail('input_invalid')
        result = wheel_move(item['move'], item['face'], faces)
        if result is None:
            _fail('move_idle')
        layout.append({'face': item['face'], 'move': item['move'], 'cost': _MOVES[item['move']][1],
                       'final_face': result[0], 'final_tier': result[1]})
    if len({entry['face'] for entry in layout}) != len(layout):
        _fail('input_invalid')
    return sorted(layout, key=lambda entry: entry['face'])


def plan_fortune(s, v):
    modifiers = _wheel_card(s)
    if type(modifiers.get(v['attribute_ref'])) is not int:
        _fail('attribute_invalid')
    modifier, dc = modifiers[v['attribute_ref']], s.rules['difficulties'][v['difficulty']]
    faces = [wheel_tier(face, modifier, dc) for face in range(1, 21)]
    layout = _wheel_layout(v.get('layout'), faces)
    chapter = _chapter(s)
    _wheel_open(s, chapter)
    echo, reserved = _wheel_echo(s, chapter), sum(entry['cost'] for entry in layout)
    if reserved > echo:
        _fail('echo_short')
    document = {'stake': v['stake'], 'attribute_ref': v['attribute_ref'], 'difficulty': v['difficulty'], 'modifier': modifier,
                'dc': dc, 'faces': faces, 'layout': layout, 'reserved': reserved, 'echo': echo, 'chapter': chapter,
                'planned_by': s.actor}
    # A new layout replaces the one still waiting; nothing was held by it.
    ops = [_update(item, 'withdrawn', item['document']) for item in s.all('fortune_plan', 'planned')
           if item['document']['planned_by'] == s.actor]
    ops.append(_create('plan', 'fortune_plan', 'planned', document, audience='members', members=[s.actor]))
    return None, {'always': ops}, '布下机运盘：%s' % v['stake']


def confirm_fortune_plan(s, v):
    plan = s.get(v['plan_ref'], 'fortune_plan', 'planned')
    d = plan['document']
    if d['planned_by'] != s.actor:
        _fail('not_drawer')
    chapter = _chapter(s)
    if _wheel_card(s).get(d['attribute_ref']) != d['modifier'] or s.rules['difficulties'].get(d['difficulty']) != d['dc'] \
            or chapter != d['chapter']:
        _fail('plan_stale')
    _wheel_open(s, chapter)
    if d['reserved'] > _wheel_echo(s, chapter):
        _fail('echo_short')
    bands, outcomes = [], {}
    for face in range(1, 21):
        key, tier = 'face%02d' % face, d['faces'][face - 1]
        bands.append({'key': key, 'low': face, 'high': face, 'label': _TIER_LABELS[tier]})
        move = next((entry for entry in d['layout'] if entry['face'] == face), None)
        wheel = {name: d[name] for name in ('attribute_ref', 'difficulty', 'modifier', 'dc', 'faces', 'layout', 'reserved', 'chapter')}
        # The platform seals the die and, on a laid-out face, opens the timed choice.
        wheel.update(plan_ref=plan['ref'], face=face, move=move, choice=None, spent=0,
                     final=None if move else {'face': face, 'tier': tier}, window=None, sealed=None)
        document = {'stake': d['stake'], 'tier': tier, 'tier_label': _TIER_LABELS[tier], 'drawn_by': s.actor, 'wheel': wheel}
        outcomes[key] = [_update(plan, 'rolled', {**d, 'face': face}),
                         _create('fortune', 'fortune', 'choosing' if move else 'frozen', document)]
    return {'sides': 20, 'bands': bands}, outcomes, '机运盘：%s' % d['stake']


def choose_fortune(s, v):
    record = s.get(v['fortune_ref'], 'fortune', 'choosing')
    d = record['document']
    wheel = d.get('wheel')
    if not wheel or d['drawn_by'] != s.actor:
        _fail('not_drawer')
    if v['choice'] == 'keep':
        kind, spent, final = 'original', 0, {'face': wheel['face'], 'tier': d['tier']}
        summary = '机运盘保留原结果：%s' % _TIER_LABELS[d['tier']]
    else:
        move, echo = wheel['move'], _wheel_echo(s, wheel['chapter'])
        kind = move['move']
        # 孤注 takes every echo left; the other moves their fixed cost.
        spent = max(1, echo) if kind == 'all_in' else move['cost']
        if spent > echo:
            _fail('echo_short')
        final = {'face': move['final_face'], 'tier': move['final_tier']}
        summary = '机运盘%s：%s → %s' % (_MOVES[kind][0], _TIER_LABELS[d['tier']], _TIER_LABELS[final['tier']])
    wheel = {**wheel, 'choice': {'kind': kind, 'by': 'player'}, 'spent': spent, 'final': final}
    document = {**d, 'tier': final['tier'], 'tier_label': _TIER_LABELS[final['tier']], 'wheel': wheel}
    return None, {'always': [_update(record, 'frozen', document)]}, summary


def set_echo(s, v):
    document = {'echo': v['echo'], 'set_by': s.actor}
    found = s.all('fortune_echo')
    op = _update(found[0], 'current', document) if found else _create('echo', 'fortune_echo', 'current', document)
    return None, {'always': [op]}, '本房每章回响起始值设为 %d' % v['echo']


# ------------------------------------------------------------ branch endings
def propose_branch(s, v):
    if s.all('ending'):
        _fail('ending_entered')
    if len(s.all('branch', 'proposed')) >= OPEN_BRANCHES:
        _fail('limit_reached')
    document = {'title': v['title'], 'description': v['description'], 'proposed_by': s.actor, 'votes': []}
    return None, {'always': [_create('branch', 'branch', 'proposed', document)]}, '提出结局分支「%s」' % v['title']


def vote_branch(s, v):
    if s.all('ending'):
        _fail('ending_entered')
    target = s.get(v['branch_ref'], 'branch', 'proposed')
    ops = []
    for record in s.all('branch', 'proposed'):
        votes = [item for item in record['document']['votes'] if item['actor_ref'] != s.actor]
        if record['ref'] == target['ref']:
            votes.append({'actor_ref': s.actor})
        if votes != record['document']['votes']:
            ops.append(_update(record, 'proposed', {**record['document'], 'votes': votes}))
    if not ops:
        _fail('already_voted')
    return None, {'always': ops}, '支持结局分支「%s」' % target['document']['title']


def enter_ending(s, v):
    if s.all('ending'):
        _fail('ending_entered')
    target = s.get(v['branch_ref'], 'branch', 'proposed')
    if {item['actor_ref'] for item in target['document']['votes']} != set(s.members):
        _fail('votes_incomplete')
    ops = [_update(record, 'chosen' if record['ref'] == target['ref'] else 'set_aside', record['document'])
           for record in s.all('branch', 'proposed')]
    document = {'branch_ref': target['ref'], 'title': target['document']['title'],
                'description': target['document']['description'], 'members': s.members, 'epilogues': []}
    return None, {'always': ops + [_create('ending', 'ending', 'entered', document)]}, '进入结局「%s」' % document['title']


def write_epilogue(s, v):
    record = s.get(v['ending_ref'], 'ending', 'entered')
    document = deepcopy(record['document'])
    if s.actor not in document['members']:
        _fail('not_member')
    if any(item['actor_ref'] == s.actor for item in document['epilogues']):
        _fail('already_written')
    document['epilogues'].append({'actor_ref': s.actor, 'text': v['text']})
    return None, {'always': [_update(record, 'entered', document)]}, '写下本人尾声'


def conclude_ending(s, v):
    record = s.get(v['ending_ref'], 'ending', 'entered')
    document = record['document']
    if {item['actor_ref'] for item in document['epilogues']} != set(document['members']):
        _fail('epilogues_incomplete')
    return None, {'always': [_update(record, 'concluded', {**document, 'concluded_by': s.actor}), {'op': 'complete_room'}]}, \
        '结局「%s」完结' % document['title']


# ----------------------------------------------------------------- outfitting
# 整备: the owner sets out finite supplies and single tools; nothing is ever
# restocked, repaired or replaced, and a second one under the same name never
# appears.  Each person claims one portion per chapter, spending one calendar
# slot; a tool has one holder at a time and comes back as the same piece, worn or
# not, unless its holder reports it lost.  Any public check may lean on a tool the
# actor holds: one tier easier, one notch of wear whatever the die says.
OUTFIT_LIMIT = 12


def _chapter(s):
    """The room's current chapter as the platform reads it (the opening act is 0)."""
    found = s.all('room_chapter')
    return found[0]['document']['number'] if found else 1


def _unique(s, kind, title):
    if any(item['document']['title'] == title for item in s.all(kind)):
        _fail('outfit_duplicate')
    if len(s.all(kind)) >= OUTFIT_LIMIT:
        _fail('limit_reached')


def stock_supply(s, v):
    _unique(s, 'supply', v['title'])
    document = {'title': v['title'], 'text': v['text'], 'stock': v['stock'], 'left': v['stock'],
                'stocked_by': s.actor, 'claims': []}
    return None, {'always': [_create('supply', 'supply', 'stocked', document)]}, '摆出物资「%s」×%d' % (v['title'], v['stock'])


def claim_supply(s, v):
    record = s.get(v['supply_ref'], 'supply', 'stocked')
    chapter = _chapter(s)
    if any(e['actor_ref'] == s.actor and e['chapter'] == chapter for item in s.all('supply') for e in item['document']['claims']):
        _fail('supply_claimed')
    calendar = _calendar(s)
    document = deepcopy(record['document'])
    document['left'] -= 1
    document['claims'].append({'actor_ref': s.actor, 'chapter': chapter, 'at': _now(calendar['document']) if calendar else 0})
    operations = [_update(record, 'stocked' if document['left'] else 'exhausted', document)]
    operations += _advance(s, 1, '领取「%s」' % document['title'])
    return None, {'always': operations}, '领取一份「%s」（余 %d / %d），用去1个时段' % (document['title'], document['left'], document['stock'])


def _tool_entry(s, document, event, **extra):
    document['log'] = (document['log'] + [{'actor_ref': s.actor, 'event': event, 'durability': document['durability'], **extra}])[-40:]


def rack_tool(s, v):
    _unique(s, 'tool', v['title'])
    document = {'title': v['title'], 'text': v['text'], 'durability_max': v['durability'], 'durability': v['durability'],
                'racked_by': s.actor, 'holder_ref': None, 'log': []}
    return None, {'always': [_create('tool', 'tool', 'racked', document)]}, '挂出工具「%s」（耐久 %d）' % (v['title'], v['durability'])


def _held(s, ref):
    record = s.get(ref, 'tool', 'borrowed')
    if record['document']['holder_ref'] != s.actor:
        _fail('not_holder')
    return record, deepcopy(record['document'])


def borrow_tool(s, v):
    record = s.get(v['tool_ref'], 'tool', 'racked')
    document = deepcopy(record['document'])
    document['holder_ref'] = s.actor
    _tool_entry(s, document, 'borrow')
    return None, {'always': [_update(record, 'borrowed', document)]}, \
        '借走「%s」（耐久 %d / %d）' % (document['title'], document['durability'], document['durability_max'])


def return_tool(s, v):
    record, document = _held(s, v['tool_ref'])
    document['holder_ref'] = None
    _tool_entry(s, document, 'return')
    worn = not document['durability']
    return None, {'always': [_update(record, 'worn' if worn else 'racked', document)]}, \
        ('归还「%s」：已磨尽，挂回架上不再外借' if worn else '原件归还「%s」') % document['title']


def report_lost(s, v):
    record, document = _held(s, v['tool_ref'])
    _tool_entry(s, document, 'lost', text=v['text'])
    return None, {'always': [_update(record, 'missing', document)]}, '登记遗失「%s」：不补发、不替换' % document['title']


def _easier(rules, difficulty):
    tiers = sorted(rules['difficulties'], key=rules['difficulties'].get)
    index = tiers.index(difficulty)
    if index == 0:
        _fail('tool_idle')
    return tiers[index - 1]


def _lean_on_tool(s, ref, rule, outcomes, summary, play, action):
    """A public check leaning on the actor's borrowed tool: one tier easier, one notch of wear either way."""
    if not isinstance(ref, str) or not 1 <= len(ref) <= 160:
        _fail('input_invalid')
    record, document = _held(s, ref)
    if document['durability'] < 1:
        _fail('tool_worn')
    easier = _easier(s.rules, rule['difficulty'])
    document['durability'] -= 1
    _tool_entry(s, document, 'use', play=play, action=action, difficulty=[rule['difficulty'], easier])
    wear = _update(record, 'borrowed', document)
    return {**rule, 'difficulty': easier}, {key: ops + [wear] for key, ops in outcomes.items()}, \
        '%s（借「%s」，难度降一档）' % (summary, document['title'])


# -------------------------------------------------------------------- catalog
T = 'text'
PLAYS = {
    'playInvestigation': {
        'note_clue': ('记录线索', note_clue, [('title', T, '标题', 120), ('text', T, '内容', 1000),
                                          ('source_kind', 'choice', '来源', ('observed', 'speaker_claim'))]),
        'search': ('搜查证据', search, [('title', T, '搜查目标', 120), ('text', T, '搜查方式', 1000)] + CHECK),
        'propose_hypothesis': ('提出假设', propose_hypothesis, [('title', T, '标题', 120), ('text', T, '推断', 1000)]),
        'weigh': ('支持／反驳', weigh, [('hypothesis_ref', 'ref', '假设', 'hypothesis'), ('clue_ref', 'ref', '线索', 'clue'),
                                    ('stance', 'choice', '立场', ('support', 'refute'))]),
        'conclude': ('得出结论', conclude, [('hypothesis_ref', 'ref', '假设', 'hypothesis'),
                                        ('verdict', 'choice', '结论', ('accept', 'reject'))]),
        'cite_fact': ('引用世界设定', cite_fact, [('fact_ref', 'ref', '公开设定', 'source_fact')]),
        'verify_hypothesis': ('核查权威来源', verify_hypothesis, [('hypothesis_ref', 'ref', '假设', 'hypothesis'), ('fact_ref', 'ref', '公开设定', 'source_fact')]),
        'question_hypothesis': ('添加待解问题', question_hypothesis, [('hypothesis_ref', 'ref', '假设', 'hypothesis'), ('question', T, '问题', 600)]),
        'split_hypothesis': ('拆分命题', split_hypothesis, [('hypothesis_ref', 'ref', '原假设', 'hypothesis'), ('title', T, '标题', 120), ('text', T, '新命题', 1000)]),
        'merge_hypotheses': ('合并待核查命题', merge_hypotheses, [('left_ref', 'ref', '第一个假设', 'hypothesis'), ('right_ref', 'ref', '第二个假设', 'hypothesis'), ('title', T, '新命题名称', 120), ('text', T, '新命题', 1000)]),
        'withdraw_hypothesis': ('本人撤回假设', withdraw_hypothesis, [('hypothesis_ref', 'ref', '假设', 'hypothesis')]),
        'apply_skill': ('技能批注', apply_skill, [('skill_ref', 'ref', '本人技能', 'skill_card'), ('fact_ref', 'ref', '公开资料', 'source_fact'),
            ('reading', T, '怎么读', 300)]),
    },
    'playTestimony': {
        'record_testimony': ('记录证词', record_testimony, [('speaker', T, '证人', 80), ('text', T, '证词', 1000)]),
        'press': ('追问', press, [('testimony_ref', 'ref', '证词', 'testimony'), ('question', T, '追问内容', 600)] + CHECK),
        'present': ('出示证据', present, [('testimony_ref', 'ref', '证词', 'testimony'), ('clue_ref', 'ref', '证据', 'clue'),
                                      ('claim', T, '指出矛盾', 600)] + CHECK),
        'annotate_testimony': ('澄清／质疑措辞', annotate_testimony, [('testimony_ref', 'ref', '证词', 'testimony'),
            ('kind', 'choice', '类型', ('clarification', 'challenge_wording')), ('text', T, '内容', 600)]),
        'compare_statement': ('对照证词', compare_statement, [('testimony_ref', 'ref', '证词', 'testimony'),
            ('other_testimony_ref', 'ref', '另一份证词', 'testimony'), ('text', T, '对照说明', 600)]),
        'withdraw_challenge': ('撤回本人质疑', withdraw_challenge, [('testimony_ref', 'ref', '证词', 'testimony'),
            ('entry', 'int', '质询序号', (1, 1000)), ('reason', T, '撤回理由', 600)]),
    },
    'playNegotiation': {
        'open_talks': ('开启交涉', open_talks, [('counterpart', T, '交涉对象', 80), ('topic', T, '议题', 300)]),
        'argue_terms': ('陈述理由', argue_terms, [('negotiation_ref', 'ref', '交涉', 'negotiation'), ('argument', T, '理由', 600)] + CHECK),
        'propose_term': ('提出条款', propose_term, [('negotiation_ref', 'ref', '交涉', 'negotiation'), ('text', T, '条款', 400)]),
        'sign_term': ('本人签署', sign_term, [('negotiation_ref', 'ref', '交涉', 'negotiation'), ('term_id', 'int', '条款', (1, 8))]),
        'settle_talks': ('达成协议', settle_talks, [('negotiation_ref', 'ref', '交涉', 'negotiation')]),
        'walk_away': ('中止交涉', walk_away, [('negotiation_ref', 'ref', '交涉', 'negotiation')]),
        'contract_context': ('交涉条件', contract_context, [('negotiation_ref', 'ref', '交涉', 'negotiation'),
            ('kind', 'choice', '类型', ('red_line', 'guarantee', 'deadline', 'remedy', 'concession', 'witness')), ('text', T, '条件', 600)]),
        'amend_term': ('替代条款', amend_term, [('negotiation_ref', 'ref', '交涉', 'negotiation'), ('term_id', 'int', '原条款', (1, 8)), ('text', T, '新条款', 400)]),
        'obligation_update': ('本人履约', obligation_update, [('negotiation_ref', 'ref', '协议', 'negotiation'), ('term_id', 'int', '条款', (1, 8)),
            ('status', 'choice', '结果', ('fulfilled', 'breached')), ('text', T, '履约或补救说明', 600)]),
        'open_deliberation': ('开启议事', open_deliberation, [('title', T, '议题', 120), ('brief', T, '简报与利益相关者', 600), ('options', 'texts', '备选方案', 6),
            ('risk', T, '已知风险与不确定后果', 600), ('impact', T, '预算与资源影响说明', 600), ('delay', 'int', '实施等待时段', (0, 12)), ('checkpoint', T, '复查节点', 300)]),
        'question_policy': ('质询议事', question_policy, [('deliberation_ref', 'ref', '议题', 'deliberation'), ('text', T, '质询', 600)]),
        'vote_policy': ('本人政策表态', vote_policy, [('deliberation_ref', 'ref', '议题', 'deliberation'), ('option', 'int', '方案序号', (1, 6))]),
        'revise_policy': ('修订议案', revise_policy, [('deliberation_ref', 'ref', '议题', 'deliberation'), ('options', 'texts', '新方案', 6)]),
        'implement_policy': ('公布议决', implement_policy, [('deliberation_ref', 'ref', '议题', 'deliberation')]),
        'review_policy': ('复查实施', review_policy, [('deliberation_ref', 'ref', '议题', 'deliberation'), ('text', T, '观察与后续', 600)]),
        'withdraw_policy': ('撤回议案', withdraw_policy, [('deliberation_ref', 'ref', '议题', 'deliberation')]),
    },
    'playRelations': {
        'appeal': ('争取态度', appeal, [('subject', T, '对象', 80), ('subject_kind', 'choice', '类型', ('npc', 'faction')),
                                     ('approach', T, '方式', 600)] + CHECK),
        'remember': ('记下往来', remember, [('subject', T, '对象', 80), ('subject_kind', 'choice', '类型', ('npc', 'faction')),
                                       ('text', T, '往来', 600)]),
        'set_goal': ('确立同伴目标', set_goal, [('companion', T, '同伴', 80), ('goal', T, '目标', 400)]),
        'resolve_goal': ('了结同伴目标', resolve_goal, [('goal_ref', 'ref', '目标', 'companion_goal'),
                                                  ('result', 'choice', '结果', ('fulfilled', 'abandoned'))]),
        'remember_dimension': ('有据的关系记忆', remember_dimension, [('subject', T, '对象', 80), ('subject_kind', 'choice', '类型', ('npc', 'faction')),
            ('clue_ref', 'ref', '来源线索', 'clue'), ('dimension', 'choice', '本人态度', ('trust', 'respect', 'fear', 'affection', 'debt', 'grievance')),
            ('change', 'int', '变化', (-1, 1)), ('text', T, '记忆与解释', 600)]),
        'companion_agenda': ('同伴议程', companion_agenda, [('goal_ref', 'ref', '同伴目标', 'companion_goal'),
            ('kind', 'choice', '类型', ('preference', 'red_line', 'concern', 'assistance', 'suggestion')), ('text', T, '议程', 600)]),
        'publish_reputation': ('传播有据说法', publish_reputation, [('subject', T, '对象', 80), ('audience_name', T, '传播受众', 120),
            ('clue_ref', 'ref', '来源线索', 'clue'), ('route', T, '见证与传播路径', 300), ('text', T, '说法', 600)]),
        'correct_reputation': ('纠正传播说法', correct_reputation, [('reputation_ref', 'ref', '原传播', 'reputation'), ('clue_ref', 'ref', '纠错依据', 'clue'), ('text', T, '纠错说明', 600)]),
    },
    'playCalendar': {
        'schedule': ('预约', schedule, [('title', T, '事项', 120), ('day', 'int', '日', (1, 365)), ('slot', 'int', '时段', (0, 3))]),
        'set_deadline': ('设定期限', set_deadline, [('title', T, '事项', 120), ('day', 'int', '日', (1, 365)),
                                                ('slot', 'int', '时段', (0, 3))]),
        'meet_deadline': ('按期完成', meet_deadline, [('deadline_ref', 'ref', '期限', 'deadline')]),
        'spend_time': ('花费时间', spend_time, [('activity', T, '活动', 200), ('slots', 'int', '时段数', (1, 4))]),
        'invite_activity': ('邀请共同活动', invite_activity, [('title', T, '活动', 120), ('day', 'int', '日', (1, 365)), ('slot', 'int', '时段', (0, 3)),
            ('slots', 'int', '占用时段', (1, 4)), ('location', T, '地点', 120), ('member_actor_refs', 'actors', '参与者', None)]),
        'respond_activity': ('本人回应邀请', respond_activity, [('appointment_ref', 'ref', '预约', 'appointment'), ('response', 'choice', '回应', ('accept', 'decline'))]),
        'reschedule_activity': ('预约改期', reschedule_activity, [('appointment_ref', 'ref', '预约', 'appointment'), ('day', 'int', '日', (1, 365)), ('slot', 'int', '时段', (0, 3))]),
        'cancel_activity': ('取消预约', cancel_activity, [('appointment_ref', 'ref', '预约', 'appointment')]),
        'attend_activity': ('参加已到期活动', attend_activity, [('appointment_ref', 'ref', '预约', 'appointment')]),
        'declare_availability': ('声明本人时段', declare_availability, [('day', 'int', '日', (1, 365)), ('slot', 'int', '时段', (0, 3)), ('slots', 'int', '时段数', (1, 4)), ('availability', 'choice', '状态', ('available', 'unavailable'))]),
        'clear_availability': ('撤回本人时段声明', clear_availability, [('availability_ref', 'ref', '时段声明', 'availability')]),
        'configure_location': ('地点开放时段', configure_location, [('location', T, '地点', 120), ('opens', 'int', '开始时段（0清晨至3夜晚）', (0, 3)), ('closes', 'int', '结束边界（1至4）', (1, 4))]),
    },
    'playProjects': {
        'start_project': ('开始项目', start_project, [('title', T, '项目', 120),
                                                  ('project_kind', 'choice', '类型', ('project', 'training')),
                                                  ('segments', 'int', '进度格', (3, 8))]),
        'work_project': ('推进项目', work_project, [('project_ref', 'ref', '项目', 'project')] + CHECK),
        'rest': ('休整', rest, []),
        'set_milestone': ('冻结里程碑', set_milestone, [('project_ref', 'ref', '项目', 'project'), ('threshold', 'int', '达到进度', (1, 8)), ('text', T, '里程碑', 400)]),
        'attempt_finish': ('提前结算项目', attempt_finish, [('project_ref', 'ref', '项目', 'project')] + CHECK),
        'claim_training': ('本人领取训练成果', claim_training, [('project_ref', 'ref', '训练项目', 'project'), ('attribute_ref', 'attribute', '成长属性', None)]),
    },
    'playConflict': {
        'open_conflict': ('开启冲突', open_conflict, [('opponent', T, '对手', 80), ('stakes', T, '赌注', 300),
                                                  ('length', 'int', '轨道长度', (3, 6))]),
        'exchange': ('交锋', exchange, [('contest_ref', 'ref', '冲突', 'contest'), ('text', T, '行动', 600)] + CHECK),
        'concede': ('让步收尾', concede, [('contest_ref', 'ref', '冲突', 'contest')]),
    },
    'playChase': {
        'open_chase': ('开始追逐', open_chase, [('quarry', T, '对象', 80), ('role', 'choice', '身份', ('pursue', 'flee')),
                                             ('distance', 'int', '初始距离', (2, 4))]),
        'exchange': ('追逐动作', exchange, [('contest_ref', 'ref', '追逐', 'contest'), ('text', T, '动作', 600)] + CHECK),
        'concede': ('放弃收尾', concede, [('contest_ref', 'ref', '追逐', 'contest')]),
    },
    'playDebate': {
        'open_debate': ('开启辩论', open_debate, [('topic', T, '辩题', 200), ('stance', T, '立场', 300),
                                              ('rounds', 'int', '回合数', (3, 6))]),
        'exchange': ('提出论据', exchange, [('contest_ref', 'ref', '辩论', 'contest'), ('text', T, '论据', 600)] + CHECK),
        'concede': ('认输收尾', concede, [('contest_ref', 'ref', '辩论', 'contest')]),
    },
    'playPlans': {
        'assess_pressure': ('主持压力评估', assess_pressure, [('ceiling', 'int', '同时压力上限（建议）', (1, 4))]),
        'request_spotlight': ('本人请求选择机会', request_spotlight, [('text', T, '想参与的内容', 600)]),
        'defer_spotlight': ('本人暂缓请求', defer_spotlight, [('request_ref', 'ref', '请求', 'spotlight_request')]),
        'recommend_spotlight': ('主持机会建议', recommend_spotlight, []),
        'invite_spotlight': ('邀请同桌选择', invite_spotlight, [('target_actor_ref', 'actor', '同桌', None), ('text', T, '邀请', 600)]),
        'respond_spotlight': ('本人回应邀请', respond_spotlight, [('invitation_ref', 'ref', '邀请', 'spotlight_invitation'), ('decision', 'choice', '回应', ('accept', 'decline'))]),
        'draft_plan': ('拟定计划', draft_plan, [('title', T, '计划', 120), ('goal', T, '目标', 400), ('steps', 'texts', '步骤', 6)]),
        'claim_step': ('认领分工', claim_step, [('plan_ref', 'ref', '计划', 'plan'), ('step', 'int', '步骤', (1, 6))]),
        'confirm_plan': ('确认计划', confirm_plan, [('plan_ref', 'ref', '计划', 'plan')]),
        'execute_step': ('执行步骤', execute_step, [('plan_ref', 'ref', '计划', 'plan'), ('step', 'int', '步骤', (1, 6))] + CHECK),
        'evacuate': ('撤离', evacuate, [('plan_ref', 'ref', '计划', 'plan')]),
        'set_extraction': ('设定撤离路线', set_extraction, [('plan_ref', 'ref', '计划', 'plan'), ('route', T, '撤离路线', 600), ('risk', T, '已知风险', 600)]),
        'revise_plan': ('另拟调整方案', revise_plan, [('plan_ref', 'ref', '原计划', 'plan'), ('title', T, '计划', 120), ('goal', T, '目标', 400), ('steps', 'texts', '重新认领的步骤', 6)]),
        'create_advantage': ('创造叙事优势', create_advantage, [('title', T, '优势', 120), ('text', T, '依据与有限效果', 600), ('clue_ref', 'ref', '已知来源', 'clue'),
            ('aspect_kind', 'choice', '类型', ('character', 'relationship', 'scene', 'consequence', 'advantage')), ('target_actor_ref', 'actor', '受益角色', None)] + CHECK),
        'invoke_aspect': ('本人调用优势', invoke_aspect, [('aspect_ref', 'ref', '优势', 'aspect'), ('plan_ref', 'ref', '计划', 'plan'), ('step', 'int', '本人步骤', (1, 6))]),
        'clear_aspect': ('本人放弃优势', clear_aspect, [('aspect_ref', 'ref', '优势', 'aspect')]),
        'offer_compel': ('提议额外困难', offer_compel, [('aspect_ref', 'ref', '叙事来源', 'aspect'), ('plan_ref', 'ref', '计划', 'plan'), ('step', 'int', '步骤', (1, 6)),
            ('target_actor_ref', 'actor', '当事人', None), ('title', T, '困难', 120), ('text', T, '具体困难', 600)]),
        'answer_compel': ('本人接受／拒绝困难', answer_compel, [('compel_ref', 'ref', '原提议', 'compel'), ('decision', 'choice', '本人决定', ('accept', 'reject'))]),
        'offer_support': ('发起援手契印', offer_support, [('skill_ref', 'ref', '本人技能', 'skill_card'), ('support_kind', 'choice', '契印', SUPPORT_KINDS),
            ('companion_actor_refs', 'actors', '同伴', None), ('text', T, '怎么撑场', 300)]),
        'answer_support': ('本人答复契印', answer_support, [('support_ref', 'ref', '契印', 'support'), ('decision', 'choice', '本人答复', ('agree', 'decline'))]),
        'seal_support': ('落印', seal_support, [('support_ref', 'ref', '契印', 'support')]),
        'end_support': ('撤回／解除契印', end_support, [('support_ref', 'ref', '契印', 'support')]),
    },
    'playFlashback': {
        'flashback': ('闪回准备', flashback, [('title', T, '准备', 120), ('preparation', T, '事先做了什么', 800)] + CHECK),
        'review_flashback': ('房主核对原历史', review_flashback, [('flashback_ref', 'ref', '闪回', 'flashback'), ('decision', 'choice', '复核', ('approve', 'reject')), ('reason', T, '核对依据与限制', 600)]),
        'use_flashback': ('使用原准备', use_flashback, [('flashback_ref', 'ref', '闪回', 'flashback'), ('plan_ref', 'ref', '行动计划', 'plan'), ('step', 'int', '本人步骤', (1, 6))]),
    },
    'playOracle': {
        'ask_oracle': ('询问神谕', ask_oracle, [('question', T, '是非问题', 300),
                                             ('likelihood', 'choice', '可能性', tuple(ORACLE_LIKELIHOOD))]),
        'configure_oracle': ('配置本房建议表', configure_oracle, [('category', 'choice', '类别', tuple(ORACLE_TABLES)), ('entries', 'texts', '建议（每行一项，最多20项）', 20)]),
        'consult_oracle': ('抽取行动／主题建议', consult_oracle, [('category', 'choice', '类别', tuple(ORACLE_TABLES)), ('question', T, '当前问题', 300)]),
    },
    'playTransformation': {
        'propose_change': ('提出转变', propose_change, [('title', T, '名称', 120), ('change', T, '变化', 800),
                                                    ('change_kind', 'choice', '类型', ('transformation', 'legacy')),
                                                    ('target_actor_ref', 'actor', '角色', None)]),
        'confirm_change': ('本人确认', confirm_change, [('transformation_ref', 'ref', '转变', 'transformation')]),
        'decline_change': ('本人拒绝', decline_change, [('transformation_ref', 'ref', '转变', 'transformation')]),
        'withdraw_change': ('撤回', withdraw_change, [('transformation_ref', 'ref', '转变', 'transformation')]),
    },
    'playPrivatePhases': {
        'open_phase': ('开启私人阶段', open_phase, [('title', T, '名称', 120), ('member_actor_refs', 'actors', '成员', None)]),
        'phase_check': ('私人检定（每人三次）', phase_check, [('phase_ref', 'ref', '阶段', 'private_phase'), ('text', T, '行动', 1000)] + CHECK),
        'phase_note': ('记录进展', phase_note, [('phase_ref', 'ref', '阶段', 'private_phase'), ('text', T, '进展', 1000)]),
        'close_phase': ('结束阶段', close_phase, [('phase_ref', 'ref', '阶段', 'private_phase')]),
    },
    'playRegroup': {
        'ready_to_regroup': ('准备汇合', ready_to_regroup, [('phase_ref', 'ref', '阶段', 'private_phase'),
                                                        ('share', T, '公开分享', 600)]),
        'regroup': ('汇合', regroup, [('phase_ref', 'ref', '阶段', 'private_phase')]),
    },
    'playOutfitting': {
        'stock_supply': ('摆出物资', stock_supply, [('title', T, '物资', 40), ('text', T, '用途', 200), ('stock', 'int', '数量', (1, 20))]),
        'rack_tool': ('挂出工具', rack_tool, [('title', T, '工具', 40), ('text', T, '用途', 200), ('durability', 'int', '耐久', (1, 5))]),
        'claim_supply': ('领取物资', claim_supply, [('supply_ref', 'ref', '物资', 'supply')]),
        'borrow_tool': ('借走工具', borrow_tool, [('tool_ref', 'ref', '工具', 'tool')]),
        'return_tool': ('原件归还', return_tool, [('tool_ref', 'ref', '工具', 'tool')]),
        'report_lost': ('登记遗失', report_lost, [('tool_ref', 'ref', '工具', 'tool'), ('text', T, '经过', 200)]),
    },
    'playFortune': {
        'draw_fortune': ('判定机运', draw_fortune, [('stake', T, '所求之事', 300)]),
        'settle_fortune': ('机运收尾', settle_fortune, [('fortune_ref', 'ref', '机运', 'fortune'), ('use', T, '如何兑现', 400)]),
        'plan_fortune': ('布下机运盘', plan_fortune, [('stake', T, '所求之事', 300)] + CHECK),
        'confirm_fortune_plan': ('确认布局并掷骰', confirm_fortune_plan, [('plan_ref', 'ref', '机运布局', 'fortune_plan')]),
        'choose_fortune': ('本人选定', choose_fortune, [('fortune_ref', 'ref', '机运', 'fortune'),
                                                      ('choice', 'choice', '本人选定', ('keep', 'use'))]),
        'set_echo': ('设定回响起始值', set_echo, [('echo', 'int', '每章回响起始值', (0, WHEEL_ECHO_MAX))]),
    },
    'playBranchEndings': {
        'propose_branch': ('提出结局分支', propose_branch, [('title', T, '结局', 120), ('description', T, '走向', 800)]),
        'vote_branch': ('支持分支', vote_branch, [('branch_ref', 'ref', '分支', 'branch')]),
        'enter_ending': ('进入结局', enter_ending, [('branch_ref', 'ref', '分支', 'branch')]),
        'write_epilogue': ('写下尾声', write_epilogue, [('ending_ref', 'ref', '结局', 'ending'), ('text', T, '尾声', 800)]),
        'conclude_ending': ('完结', conclude_ending, [('ending_ref', 'ref', '结局', 'ending')]),
    },
}
# Optional fields: the heir only exists for a legacy.
for _play in CONTESTS:
    PLAYS[_play].update({
        'join_contest': ('本人加入对抗', join_contest, [('contest_ref', 'ref', '对抗', 'contest')]),
        'prepare_position': ('争取有利位置', prepare_position, [('contest_ref', 'ref', '对抗', 'contest'), ('text', T, '准备方法', 600)] + CHECK),
        'maneuver': ('选择风险与效果', maneuver, [('contest_ref', 'ref', '对抗', 'contest'), ('text', T, '行动', 600),
            ('position', 'choice', '位置／效果', ('controlled', 'risky', 'desperate'))] + CHECK),
    })
# 合力险关 follows the conflict's own contest actions, so their catalog order stays as it was.
PLAYS['playConflict'].update({
    'form_joint': ('立下合力险关', form_joint, [('title', T, '险关', 80), ('text', T, '局面', 600),
        ('front_a', T, '第一路', 24), ('attributes_a', 'attributes', '第一路可用属性', 3),
        ('front_b', T, '第二路', 24), ('attributes_b', 'attributes', '第二路可用属性', 3),
        ('difficulty', 'difficulty', '难度', None), ('size', 'int', '人数上限', (2, 5)),
        ('harm', 'int', '失守伤势', (0, 3)), ('fact', T, '过关后确立的事实', 300),
        ('front', 'choice', '本人守哪一路', JOINT_FRONTS)]),
    'join_joint': ('认领一路', join_joint, [('joint_ref', 'ref', '险关', 'joint'), ('front', 'choice', '守哪一路', JOINT_FRONTS)]),
    'roll_joint': ('守住本路', roll_joint, [('joint_ref', 'ref', '险关', 'joint'), ('attribute_ref', 'attribute', '属性', None),
        ('text', T, '怎么守', 300)]),
    'settle_joint': ('收尾险关', settle_joint, [('joint_ref', 'ref', '险关', 'joint')]),
})
PLAYS['playDebate'].update({
    'prepare_arguments': ('启用本人论据动作库', prepare_arguments, [('contest_ref', 'ref', '辩论', 'contest')]),
    'refresh_arguments': ('补充论据手牌', refresh_arguments, [('deck_ref', 'ref', '本人动作库', 'argument_deck')]),
    'play_argument': ('打出论据方法', play_argument, [('deck_ref', 'ref', '本人动作库', 'argument_deck'), ('method', 'choice', '方法', ARGUMENTS),
        ('clue_ref', 'ref', '论证来源', 'clue'), ('text', T, '论证', 600)] + CHECK),
})
# A negotiating seal: the offerer and each companion who agrees write their own terms.
_TERM_FIELDS = [('want', T, '我们要的', 200), ('red_line', T, '底线', 200), ('exit', T, '退出方式', 200)]
OPTIONAL = {('playTransformation', 'propose_change'): [('heir_actor_ref', 'actor', '继承者', None)],
            ('playPlans', 'offer_support'): _TERM_FIELDS, ('playPlans', 'answer_support'): _TERM_FIELDS,
            # A danger may also move one public world clock when it is lost.
            ('playConflict', 'form_joint'): [('clock_ref', 'ref', '失守时推进的世界时钟', 'world_clock')],
            # A wheel may be rolled with nothing laid out.
            ('playFortune', 'plan_fortune'): [('layout', 'layout', '布局', (WHEEL_FACES, tuple(_MOVES)))]}
CONTEST_ACTIONS = {'exchange', 'concede', 'join_contest', 'prepare_position', 'maneuver'}
# Record kinds each play reads, beyond its own: testimony presents investigation
# clues, projects spend the calendar, regroup works on private phases, a joint
# danger may move a public world clock and leaves a clue when it is cleared.
READS = {
    'playInvestigation': ('clue', 'hypothesis', 'source_fact', 'skill_card', 'skill_note'), 'playTestimony': ('testimony', 'clue'),
    'playNegotiation': ('negotiation', 'deliberation', 'calendar'), 'playRelations': ('relation', 'companion_goal', 'clue', 'reputation'),
    'playCalendar': ('calendar', 'appointment', 'deadline', 'availability', 'location_window'),
    'playProjects': ('project', 'calendar', 'appointment', 'deadline'),
    'playOutfitting': ('supply', 'tool', 'room_chapter', 'calendar', 'appointment', 'deadline'),
    'playConflict': ('contest', 'joint', 'world_clock', 'clue'), 'playChase': ('contest',), 'playDebate': ('contest', 'argument_deck', 'clue'), 'playPlans': ('plan', 'aspect', 'compel', 'clue', 'contest', 'host_context', 'pressure_advice', 'spotlight_request', 'spotlight_advice', 'spotlight_invitation', 'support', 'skill_card'),
    'playFlashback': ('flashback', 'flashback_review', 'source_fact', 'source_event', 'plan'), 'playOracle': ('oracle', 'oracle_table'), 'playTransformation': ('transformation',),
    'playPrivatePhases': ('private_phase', 'private_note', 'private_check'), 'playRegroup': ('private_phase', 'regroup'),
    'playFortune': ('fortune', 'fortune_plan', 'fortune_echo', 'attribute_card', 'room_chapter'),
    'playBranchEndings': ('branch', 'ending'),
}
# 整备: any public check may lean on a tool the actor borrowed, so every play with
# one reads tools.  Training is claimed without a die; a private phase check stays
# private, and a public tool's wear would give it away.  A wheel names its check
# when it is laid out and rolls only at confirmation, so it is not a check itself.
TOOL_FIELD = ('tool_ref', 'ref', '借来的工具', 'tool')
NOT_CHECKS = ('claim_training', 'plan_fortune')
TOOL_CHECKS = frozenset((play, action) for play, actions in PLAYS.items() for action, (_, _, fields) in actions.items()
                        if action not in NOT_CHECKS + ('phase_check',) and any(name == 'attribute_ref' for name, *_ in fields))
for _play in sorted({play for play, _ in TOOL_CHECKS}):
    if 'tool' not in READS[_play]:
        READS[_play] += ('tool',)


def _field_extra(kind, option):
    return ({'maximum': option} if kind in {'text', 'texts', 'attributes'} else
            {'maximum': option[0], 'options': list(option[1])} if kind == 'layout' else
            {'options': list(option)} if kind == 'choice' else
            {'minimum': option[0], 'maximum': option[1]} if kind == 'int' else
            {'record_kind': option} if kind == 'ref' else {})


def catalog(payload=None):
    if payload not in (None, {}):
        _fail('request_invalid')
    plays = {}
    for play, actions in PLAYS.items():
        plays[play] = {'reads': list(READS[play]), 'actions': {
            action: {'label': label, 'fields': [
                {'name': name, 'type': kind, 'label': text, 'required': True,
                 **_field_extra(kind, option)}
                for name, kind, text, option in fields] + [
                {'name': name, 'type': kind, 'label': text, 'required': False, **_field_extra(kind, option)}
                for name, kind, text, option in OPTIONAL.get((play, action), []) + ([TOOL_FIELD] if (play, action) in TOOL_CHECKS else [])],
                'check': action not in NOT_CHECKS and any(name == 'attribute_ref' for name, *_ in fields),
                # Hosts may re-serialize this object with sorted keys; the natural order travels here.
                'order': index}
            for index, (action, (label, _, fields)) in enumerate(actions.items())}}
    return {'schema': CATALOG_SCHEMA, 'feature': FEATURE, 'plays': plays, 'slots': list(SLOTS),
            'flashback_budget': FLASHBACK_BUDGET}


def _records(value, play):
    if not isinstance(value, list) or len(value) > 2000:
        _fail('request_invalid')
    for item in value:
        if not isinstance(item, dict) or set(item) != {'ref', 'kind', 'revision', 'state', 'document'} \
                or item['kind'] not in READS[play] or not isinstance(item['document'], dict) \
                or type(item['revision']) is not int:
            _fail('request_invalid')
    return value


def evaluate(payload):
    """One requested action against committed records → an uncommitted proposal."""
    required = {'play', 'action', 'input', 'actor_ref', 'member_refs', 'records', 'rules'}
    if not isinstance(payload, dict) or set(payload) != required:
        _fail('request_invalid')
    play, action = payload['play'], payload['action']
    if play not in PLAYS or action not in PLAYS[play]:
        _fail('action_unknown')
    rules = payload['rules']
    if not isinstance(rules, dict) or not isinstance(rules.get('attributes'), dict) or not isinstance(rules.get('difficulties'), dict):
        _fail('rules_invalid')
    members = payload['member_refs']
    if not isinstance(members, list) or payload['actor_ref'] not in members:
        _fail('actor_invalid')
    _records(payload['records'], play)
    label, handler, fields = PLAYS[play][action]
    optional = OPTIONAL.get((play, action), [])
    raw = payload['input']
    names = {name for name, *_ in fields}
    tool = raw.get('tool_ref') if isinstance(raw, dict) and (play, action) in TOOL_CHECKS else None
    lean = {'tool_ref'} if (play, action) in TOOL_CHECKS else set()
    if not isinstance(raw, dict) or not names <= set(raw) <= names | {name for name, *_ in optional} | lean:
        _fail('input_invalid')
    value = {name: _field(raw[name], kind, option, rules, members) for name, kind, _, option in fields}
    for name, *_ in optional:
        value[name] = raw.get(name)
    scope = _Scope(payload)
    result = handler(scope, value, play) if action in CONTEST_ACTIONS else handler(scope, value)
    rule, outcomes, summary = result
    if tool is not None:
        if not rule or 'attribute_ref' not in rule:
            _fail('tool_idle')
        rule, outcomes, summary = _lean_on_tool(scope, tool, rule, outcomes, summary, play, action)
        value['tool_ref'] = tool
    draw = rule if rule and 'bands' in rule else None
    check = rule if rule and 'attribute_ref' in rule else None
    return {'schema': PROPOSAL_SCHEMA, 'committed': False, 'play': play, 'action': action, 'label': label,
            'summary': summary, 'input': value, 'check': check, 'draw': draw, 'outcomes': outcomes}


__all__ = ['FEATURE', 'CATALOG_METHOD', 'EVALUATE_METHOD', 'CATALOG_SCHEMA', 'PROPOSAL_SCHEMA', 'PLAYS', 'READS',
           'WHEEL_TIERS', 'WHEEL_MOVES', 'wheel_tier', 'wheel_move',
           'TOOL_CHECKS', 'CustomPlayError', 'catalog', 'evaluate']
