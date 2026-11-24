from uuid import uuid4


class ModelError(ValueError):
    def __init__(self,message,*,code='unknown',details='',reference=None):
        super().__init__(message)
        self.code,self.details,self.reference=code,details,reference or uuid4().hex[:10]

    def diagnostic(self):
        return dict(code=self.code,details=self.details,reference=self.reference)


class IncompleteGeneration(ModelError):
    def __init__(self,message,*,partial_text='',code='incomplete',details=''):
        super().__init__(message,code=code,details=details)
        self.partial_text=partial_text


def incomplete_error(result,elapsed,task,api_mode='responses'):
    if api_mode=='chat':
        choice=result.choices[0] if result.choices else None
        reason=choice.finish_reason if choice else 'missing_choice'
        partial=choice.message.content or '' if choice else ''
        status='incomplete'
    else:
        status=str(result.status)
        info=getattr(result,'incomplete_details',None)
        reason=getattr(info,'reason',None) or 'not_reported'
        partial=getattr(result,'output_text','') or '' if status=='incomplete' else ''
    exhausted=reason in ('max_output_tokens','length')
    code='output_limit' if exhausted else 'incomplete'
    message='模型输出额度已用完，正文尚未完成。可降低正文思考强度或缩短本章目标；增加超时不能补足输出额度。' if exhausted else '模型返回了未完成结果，具体原因请查看详情；未将其视为完整正文。'
    # 仅记录已知枚举、用量数值；不保存推理内容、原始响应或服务端消息。
    known=reason if reason in ('max_output_tokens','length','content_filter','not_reported','missing_choice','tool_calls') else 'other'
    usage=getattr(result,'usage',None)
    input_tokens=getattr(usage,'input_tokens',getattr(usage,'prompt_tokens',None))
    output_tokens=getattr(usage,'output_tokens',getattr(usage,'completion_tokens',None))
    token_details=getattr(usage,'output_tokens_details',getattr(usage,'completion_tokens_details',None))
    reasoning=getattr(token_details,'reasoning_tokens',None)
    def number(value):return value if isinstance(value,int) else '未提供'
    details=f'任务：{task}\n状态：{status if status in ("incomplete","failed","cancelled","queued","in_progress") else "other"}\n未完成原因：{known}\n输入 tokens：{number(input_tokens)}\n输出 tokens：{number(output_tokens)}\n其中思考 tokens：{number(reasoning)}\n已返回正文字符数：{len(partial.strip())}\n耗时：{elapsed:.1f} 秒'
    return IncompleteGeneration(message,partial_text=partial,code=code,details=details)


def transport_error(exc,timeout,elapsed,task,attempt):
    from openai import APITimeoutError,APIStatusError
    status=getattr(exc,'status_code',None)
    if isinstance(exc,APITimeoutError):
        code='timeout';message=f'等待模型响应超过 {timeout:g} 秒，当前请求未完成。可在模型设置中增加超时后重试。'
    elif isinstance(exc,APIStatusError):
        body=getattr(exc,'body',None)
        error=body.get('error',body) if isinstance(body,dict) else {}
        quota=isinstance(error,dict) and error.get('code') in ('insufficient_quota','quota_exceeded')
        code={401:'authentication',403:'permission',404:'endpoint',408:'timeout',429:'quota' if quota else 'rate_limit'}.get(status,'server' if status and status>=500 else 'request')
        message={'authentication':'密钥未通过验证（401），请检查密钥所属平台及 API 地址。','permission':'接口拒绝访问（403），请检查模型权限和地域。','endpoint':'模型或接口地址不可用（404），请检查模型名称与接口协议。','timeout':'模型服务等待超时（408），请稍后重试。','quota':'API 可用额度不足（429），请在服务商平台检查额度。','rate_limit':'模型请求受到限流（429），请稍候再试；暂不能认定额度不足。','server':'模型服务暂时异常，请稍后重试。','request':f'模型未接受请求（{status}），请检查模型与接口协议是否兼容。'}[code]
    else:
        code='connection';message='未能连接模型服务，暂未确认是网络、代理还是证书问题。请检查连接后重试。'
    cause=exc.__cause__
    # 仅记录类别和数值，不保存服务端原始错误消息、请求内容、地址或密钥。
    details=f'任务：{task}\n异常：{type(exc).__name__}\n底层类别：{type(cause).__name__ if cause else "未知"}\nHTTP：{status or "无响应状态码"}\n本次耗时：{elapsed:.1f} 秒\n已尝试：{attempt} 次'
    return ModelError(message,code=code,details=details)
