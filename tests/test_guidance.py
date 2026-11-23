import httpx
import pytest
from app.guidance import explain_error,chapter_checklist
from models.domain import State,Project,Chapter,Document
from llm.client import ModelError
from test_llm import writer_for


def test_legacy_network_failure_does_not_guess_timeout_or_quota():
    issue=explain_error('模型请求失败（network）',memory=True)
    assert '不足以判断' in issue.explanation
    assert issue.settings and '正文已保存' in issue.title
    assert 'network' not in issue.explanation


def test_budget_error_does_not_recommend_longer_timeout():
    issue=explain_error('超出预算',dict(code='budget'),True)
    assert '增加请求超时不能解决' in issue.explanation
    assert not issue.settings


def test_checklist_distinguishes_outline_missing_and_memory_failure():
    state=State(project=Project(title='测试'))
    state.chapters[2]=Chapter(number=2)
    text,ready=chapter_checklist(state,2)
    assert not ready and '本章规划' in text
    state.documents['outline:2']=Document(approved='正式大纲')
    assert chapter_checklist(state,2)[1]
    state.memory_status='failed'
    text,ready=chapter_checklist(state,2)
    assert not ready and '重试整理记忆' in text and '无需重新定稿' in text


@pytest.mark.parametrize('failure,expected', [('timeout','timeout'),('connection','connection'),('401','authentication'),('429','rate_limit'),('quota','quota')])
async def test_errors_are_classified_without_leaking_transport_text(monkeypatch,failure,expected,caplog):
    async def no_sleep(_):pass
    monkeypatch.setattr('llm.client.asyncio.sleep',no_sleep)
    def handler(request):
        if failure=='timeout':raise httpx.ReadTimeout('private-test-key must not be logged',request=request)
        if failure=='connection':raise httpx.ConnectError('private-test-key must not be logged',request=request)
        status=401 if failure=='401' else 429
        return httpx.Response(status,json={'error':{'code':'insufficient_quota' if failure=='quota' else 'rate_limit','message':'private-test-key'}})
    writer=writer_for(handler)
    try:
        with pytest.raises(ModelError) as caught:await writer.text('chapter','{}')
        error=caught.value
        assert error.code==expected
        assert error.reference and '异常：' in error.details
        assert 'private-test-key' not in str(error)+error.details+caplog.text
    finally:await writer.client.close()
