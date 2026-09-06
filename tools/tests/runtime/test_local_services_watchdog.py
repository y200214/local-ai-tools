import pytest
import local_services_watchdog as watch


@pytest.mark.parametrize('state,ports,expected', [
    ({'state':'Ready','enabled':True}, [False,False], 'stopped'),
    ({'state':'Running','enabled':True}, [False,False], 'running_unavailable'),
    ({'state':'Ready','enabled':True}, [True,False], 'partial_listener'),
    ({'state':'Ready','enabled':True}, [True,True], 'healthy'),
    ({'state':'Disabled','enabled':False}, [False,False], 'maintenance'),
    ({'state':'Unknown','enabled':True}, [False,False], 'unknown_state'),
])
def test_decision(state, ports, expected):
    assert watch.decide(state, ports) == expected


@pytest.mark.parametrize('fix', [True, False])
def test_stopped_recovery(monkeypatch, fix):
    started, events = [], []
    monkeypatch.setattr(watch, 'task_state', lambda: {'state':'Ready','enabled':True,'last_result':123})
    monkeypatch.setattr(watch, 'reachable', lambda p: bool(started))
    monkeypatch.setattr(watch, 'start_task', lambda: started.append(True))
    monkeypatch.setattr(watch, 'record', lambda e,s,p: events.append(e))
    monkeypatch.setattr(watch.time, 'sleep', lambda _: None)
    assert watch.check(fix) == ('recovered' if fix else 'stopped')
    assert len(started) == int(fix)
    assert events[0] == 'stopped'


@pytest.mark.parametrize('state', ['Running','Disabled','Unknown'])
def test_never_restart_running_or_disabled(monkeypatch, state):
    monkeypatch.setattr(watch, 'task_state', lambda: {'state':state,'enabled':state!='Disabled'})
    monkeypatch.setattr(watch, 'reachable', lambda _: False)
    monkeypatch.setattr(watch, 'record', lambda *a: None)
    monkeypatch.setattr(watch, 'start_task', lambda: pytest.fail('must not start'))
    watch.check(True)


def test_state_change_before_start(monkeypatch):
    states = iter([{'state':'Ready','enabled':True}, {'state':'Running','enabled':True}])
    monkeypatch.setattr(watch, 'task_state', lambda: next(states))
    monkeypatch.setattr(watch, 'reachable', lambda _: False)
    monkeypatch.setattr(watch, 'record', lambda *a: None)
    monkeypatch.setattr(watch, 'start_task', lambda: pytest.fail('must not start'))
    assert watch.check(True) == 'state_changed'


def test_start_not_confirmed(monkeypatch):
    events = []
    monkeypatch.setattr(watch, 'task_state', lambda: {'state':'Ready','enabled':True})
    monkeypatch.setattr(watch, 'reachable', lambda _: False)
    monkeypatch.setattr(watch, 'record', lambda e,s,p: events.append(e))
    monkeypatch.setattr(watch, 'start_task', lambda: None)
    monkeypatch.setattr(watch.time, 'sleep', lambda _: None)
    assert watch.check(True) == 'start_unconfirmed'
    assert 'recovered' not in events


def test_logs_only_selected_fields(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(watch, 'LOG', tmp_path / 'watch.jsonl')
    watch.record('stopped', {'state':'Ready','last_result':123,'secret':'do not log'}, [False,False])
    data = json.loads(watch.LOG.read_text(encoding='utf-8'))
    assert data['last_result'] == 123
    assert 'secret' not in data
    assert 'do not log' not in watch.LOG.read_text(encoding='utf-8')
