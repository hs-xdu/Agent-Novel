from dataclasses import dataclass
from llm.errors import ModelError


@dataclass
class Issue:
    title: str
    explanation: str
    next_step: str
    details: str
    settings: bool = False


def explain_error(message,diagnostic=None,memory=False):
    diagnostic=diagnostic or {}
    code=diagnostic.get('code','unknown')
    legacy='network' in message
    explanation={
        'timeout':message,
        'connection':'未能完成模型连接。尚未确定是网络、代理还是证书问题。',
        'authentication':'密钥未通过验证，请确认密钥和地址属于同一平台及地域。',
        'permission':'当前账号或密钥没有访问该模型的权限。',
        'endpoint':'模型名称、API 地址或接口协议可能不匹配。',
        'quota':'服务商返回了额度不足的错误，请检查 API 可用额度。',
        'rate_limit':'服务商限制了本次请求频率。请稍候再试，不能据此认定余额不足。',
        'server':'模型服务暂时异常，请稍后重试。',
        'configuration':'尚未配置可用的模型名称或密钥。',
        'budget':'输入资料超过当前上下文预算。这是本地检查，增加请求超时不能解决。',
        'output_limit':'模型已达到输出额度上限，尚未完成生成。思考内容可能占用输出额度，增加超时不能补足额度。',
        'incomplete':'模型返回未完成结果；请查看具体状态和原因。已返回的部分正文会另存为未完成候选（如有）。',
        'memory_review':'记忆候选需要审阅，或发现了人物关系、设定冲突。',
    }.get(code,'上次请求未完成，历史记录不足以判断具体原因。' if legacy else message or '记忆尚未整理完成，或上次任务被中断。')
    settings=code in ('timeout','connection','authentication','permission','endpoint','configuration','request','output_limit','incomplete') or legacy
    next_step={'timeout':'打开模型设置，适当增加超时（例如 300 秒），保存后重试。',
               'budget':'在详情中查看预算错误；精简必要资料或调整上下文预算后重试。',
               'output_limit':'打开模型设置，将正文思考强度调整为低或关闭，或缩短本章目标后重试；整章生成如已返回正文，可在正文审阅中查看未完成候选。',
               'incomplete':'先查看详情；如有未完成候选，可审阅后采用为草稿并手动补全。',
               'memory_review':'到“小说记忆”审阅候选和冲突，确认后重试整理记忆。',
               'quota':'检查服务商 API 额度后重试。','rate_limit':'等待一会儿，再重试当前任务。'}.get(code,'检查模型设置并测试连接，然后重试。' if settings else '稍后重试；仍失败可提供错误编号供排查。')
    if code=='output_limit' and (memory or '任务：memory' in diagnostic.get('details','')):
        explanation='记忆整理达到输出额度上限，尚未返回完整记忆。已定稿正文仍保留；增加超时不能补足输出额度。'
        next_step='打开模型设置，将“记忆整理思考强度”设为关闭，保存后重试整理记忆；无需重写或重新定稿正文。'
    reference=diagnostic.get('reference','历史记录未提供')
    details=f'错误编号：{reference}\n类别：{code}\n'+diagnostic.get('details','未记录底层信息')
    return Issue('正文已保存，记忆整理未成功' if memory else '本次生成未完成',explanation,next_step,details,settings)


def memory_issue(state):
    return explain_error(state.memory_error,state.memory_diagnostic,True)


def chapter_checklist(state,number):
    c=state.chapters.get(number);doc=state.documents.get(f'outline:{number}')
    checks=[('章节已建立',c is not None),('本章大纲已确认',bool(doc and doc.approved)),('前文记忆已同步',state.memory_status=='synced')]
    text='   '.join(('✓ ' if done else '○ ')+label for label,done in checks)
    if state.memory_status!='synced':next_step='先重试整理记忆；正文已保存，无需重新定稿。'
    elif not c:next_step='点击左侧“开始下一章”，或填写本章目标生成大纲。'
    elif not doc or not doc.approved:next_step='在“本章规划”生成并确认大纲。'
    elif c.draft_incomplete:next_step='当前是未完成草稿，请编辑补全后再确认定稿。'
    elif not c.draft:next_step='大纲已确认，可以生成正文。'
    elif c.final and c.draft==c.final:next_step='本章已完成，可以开始下一章。'
    else:next_step='正文草稿已保存，审阅满意后确认定稿。'
    return text+'\n下一步：'+next_step,bool(c and doc and doc.approved and state.memory_status=='synced')
