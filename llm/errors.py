from uuid import uuid4


class ModelError(ValueError):
    def __init__(self,message,*,code='unknown',details='',reference=None):
        super().__init__(message)
        self.code,self.details,self.reference=code,details,reference or uuid4().hex[:10]

    def diagnostic(self):
        return dict(code=self.code,details=self.details,reference=self.reference)


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
