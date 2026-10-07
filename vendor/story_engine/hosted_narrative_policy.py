"""Brief-story narrative preferences, compiled in the existing main call."""
from .brief_start import _object, _text

LEGACY_RANGES={'minimal':(350,600),'balanced':(700,1200),'epic':(1400,2600)}
RANGES={'minimal':(100,300),'balanced':(300,600),'epic':(600,1000)}
LEGACY_SCHEMA='321roll-hosted-narrative-policy/1.0.0'
SCHEMA='321roll-hosted-narrative-policy/2.0.0'
PRESETS={'dialogue_high':'多对白','dialogue_soft':'偏对白','balanced':'均衡','description_soft':'偏描写','description_high':'多描写'}

def options():
    return {'schema':'se-hosted-narrative-policy-options/2.0.0','modes':{k:list(v) for k,v in RANGES.items()},'presets':PRESETS,'additional_model_calls':0}

def ranges(policy):
    # A missing schema is accepted only by the internal legacy length helper;
    # compile_context validates every incoming frozen policy before using it.
    schema=policy.get('schema',LEGACY_SCHEMA)
    if schema==LEGACY_SCHEMA:return LEGACY_RANGES
    if schema==SCHEMA:return RANGES
    raise ValueError('hosted_turn.narrative_policy_invalid')

def validate(value):
    _object(value,('schema','revision','mode','preset','style'))
    if value['schema'] not in {LEGACY_SCHEMA,SCHEMA} or type(value['revision']) is not int or value['revision']<1 or value['mode'] not in RANGES or value['preset'] not in PRESETS:
        raise ValueError('hosted_turn.narrative_policy_invalid')
    _text(value['style'],600)
    return dict(value)

def instruction(policy):
    low,high=ranges(policy)[policy['mode']]
    legacy=policy.get('schema',LEGACY_SCHEMA)==LEGACY_SCHEMA
    paragraphs=({'minimal':'2至4','balanced':'4至6','epic':'6至8'} if legacy else {'minimal':'1至2','balanced':'2至4','epic':'4至6'})[policy['mode']]
    shape=({'minimal':'建议写3段，每段约140至180字。','balanced':'建议写5段，每段约160至210字。','epic':'建议写7段，每段约230至320字。'} if legacy else {'minimal':'简洁呈现行动回应。','balanced':'清楚呈现行动、人物回应与后果。','epic':'展开已发生的行动和可观察细节，保持节奏紧凑。'})[policy['mode']]
    counting=(f'本次已冻结的正文篇幅必须是 {low}—{high} 个可见中文字符，以 {(low+high)//2} 字为写作目标，建议 {paragraphs} 个自然段；只计算 paragraphs 正文，不计选项、facts 和机械结果。' if legacy else f'本次已冻结的正文篇幅必须是 {low}—{high} 个可见字符，以 {(low+high)//2} 字为写作目标，建议 {paragraphs} 个自然段；只计算 paragraphs 正文，不计空白、选项、facts 和独立机械结果，正文标点计入。')
    return (counting+
            f'对白与描写比例为“{PRESETS[policy["preset"]]}”。文风期望：{policy["style"]}。'
            +shape+
            '输出前在同一次生成内检查总篇幅，不输出统计或思考过程。可以展开已经发生的行动、可观察细节和人物回应，不得为补足字数自动执行额外行动或重复段落。'
            '篇幅和文风仅影响表达，不改变规则、事实、玩家权限、内容边界或已提交结算。')

def validate_length(paragraphs,policy):
    low,high=ranges(policy)[policy['mode']]
    count=sum(not ch.isspace() for paragraph in paragraphs for ch in paragraph)
    if not low<=count<=high:
        raise ValueError(f'hosted_turn.narrative_length_invalid actual={count} minimum={low} maximum={high}')
