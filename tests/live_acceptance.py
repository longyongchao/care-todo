"""真实 Ollama 验收。隔离临时数据库，不改变演示数据。需要本机模型就绪。"""
import json
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import CareApp, now


def run():
    with tempfile.TemporaryDirectory(prefix='care-live-') as folder:
        app = CareApp(Path(folder) / 'test.sqlite3')
        health = app.model.health()
        print(json.dumps(health, ensure_ascii=False), flush=True)
        if not health['ok']:
            raise RuntimeError(health['message'])
        script = [
            ('caregiver', '请把上周的记录发给我，我收到后核对是否齐全，再回复您。'),
            ('patient', '好的，我明天发。'),
            ('patient', '我已经发过去了。'),
            ('caregiver', '收到了，已经核对，记录都齐全。'),
        ]
        report = []
        for index, (role, content) in enumerate(script, 1):
            with app.db() as con:
                mid = con.execute('INSERT INTO messages(patient_id,role,content,created_at) VALUES(1,?,?,?)', (role, content, now())).lastrowid
            start = time.monotonic()
            app.analyze(1, mid)
            tasks = app.state()['tasks']
            report.append({'step': index, 'seconds': round(time.monotonic()-start, 2), 'message': content, 'tasks': tasks})
            print(json.dumps(report[-1], ensure_ascii=False), flush=True)
            assert len(tasks) == 2, f'第 {index} 步不应重复或遗漏待办：{tasks}'
            by_owner = {t['owner']: t for t in tasks}
            assert set(by_owner) == {'patient', 'caregiver'}, '双方责任混淆'
            assert all(t['status'] != 'completed' for t in tasks), '模型不得自动完成事项'
            if index <= 2:
                assert all(t['status']=='pending' for t in tasks), '把承诺当成完成'
            if index == 2:
                assert '明天' in by_owner['patient']['due'], '遗漏约定时间'
            if index == 3:
                assert by_owner['patient']['status']=='possible' and by_owner['caregiver']['status']=='pending', '发送和核对混淆'
            if index == 4:
                assert by_owner['caregiver']['status']=='possible', '未识别核对并回复的完成线索'
        task = next(t for t in app.state()['tasks'] if t['owner']=='caregiver')
        app.edit_task(task['id'], 'confirm')
        assert next(t for t in app.state()['tasks'] if t['id']==task['id'])['status']=='completed'
        print('PASS: 产品文档四句对话与人工确认完成。', flush=True)
        # 实际调用患者模拟，验证主动提问/自动回复流水线与不同患者隔离。
        job = app.submit(2, proactive=True)
        app.run_job(job['id'])
        snapshot = app.state()
        assert not snapshot['jobs'], snapshot['jobs']
        assert len([m for m in snapshot['messages'] if m['patient_id']==2]) == 1
        print('PASS: 患者主动提问与自动观察', flush=True)
        job = app.submit(2, '我明天帮您确认预约安排，确认后告诉您。')
        app.run_job(job['id'])
        snapshot = app.state()
        assert not snapshot['jobs'], snapshot['jobs']
        assert len([m for m in snapshot['messages'] if m['patient_id']==2]) == 3
        assert len([t for t in snapshot['tasks'] if t['patient_id']==1]) == 2
        print('PASS: 照护师发送、患者自动回复、双方消息检查、患者隔离。', flush=True)

if __name__ == '__main__':
    run()
