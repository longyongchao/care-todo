import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import CareApp, now
from ollama_client import ModelError


def change(mid, owner='caregiver', title='核对上周记录并回复', signal='pending', task_id=None):
    return dict(id=task_id, owner=owner, title=title, due='', signal=signal, reason='测试依据', remaining='', evidence=[mid])


class FakeModel:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []
    def chat(self, messages, schema=None):
        self.calls.append((messages, schema))
        result = self.responses.pop(0)
        if isinstance(result, Exception): raise result
        return result


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'care.sqlite3'
        self.app = CareApp(self.path, FakeModel())
    def tearDown(self):
        self.folder.cleanup()
    def message(self, text='测试', patient=1, role='caregiver'):
        with self.app.db() as con:
            return con.execute('INSERT INTO messages(patient_id,role,content,created_at) VALUES(?,?,?,?)', (patient,role,text,now())).lastrowid
    def apply(self, mid, *changes, patient=1):
        self.app.apply_analysis(patient, mid, {'changes': list(changes)})
    def task(self, task_id=None):
        return next(t for t in self.app.state()['tasks'] if task_id is None or t['id']==task_id)

    def test_spec_sequence_human_only_completion(self):
        first = self.message('请把上周的记录发给我，我收到后核对是否齐全，再回复您。')
        self.apply(first, change(first, 'patient', '发送上周记录'), change(first))
        tasks = {t['owner']: t for t in self.app.state()['tasks']}
        second = self.message('好的，我明天发。', role='patient')
        c = change(second, 'patient', '发送上周记录', task_id=tasks['patient']['id']); c['due'] = '明天'
        self.apply(second, c)
        self.assertTrue(all(t['status']=='pending' for t in self.app.state()['tasks']))
        third = self.message('我已经发过去了。', role='patient'); c.update(evidence=[third], signal='possible')
        self.apply(third, c)
        self.assertEqual(self.task(tasks['patient']['id'])['status'], 'possible')
        self.assertEqual(self.task(tasks['caregiver']['id'])['status'], 'pending')
        fourth = self.message('收到了，已经核对，记录都齐全。')
        self.apply(fourth, change(fourth, signal='possible', task_id=tasks['caregiver']['id']))
        self.assertEqual(len(self.app.state()['tasks']), 2)
        self.assertFalse(any(t['status']=='completed' for t in self.app.state()['tasks']))
        self.app.edit_task(tasks['caregiver']['id'], 'confirm')
        self.assertEqual(self.task(tasks['caregiver']['id'])['status'], 'completed')

    def test_atomic_invalid_model_result_rolls_back_everything(self):
        mid = self.message()
        with self.assertRaises(ModelError): self.apply(mid, change(mid), change(mid, title='第二件事', signal='completed'))
        self.assertEqual(self.app.state()['tasks'], [])
        with self.app.db() as con: self.assertEqual(con.execute('SELECT count(*) FROM analyses').fetchone()[0], 0)

    def test_cross_patient_and_future_evidence_rejected(self):
        mid = self.message(); other = self.message(patient=2)
        for invalid in ([other], [mid, other], [mid+100]):
            c = change(mid); c['evidence'] = invalid
            with self.assertRaises(ModelError): self.apply(mid, c)
        self.assertEqual(self.app.state()['tasks'], [])

    def test_dedup_same_title_and_idempotent_processing(self):
        first = self.message(); self.apply(first, change(first))
        second = self.message(); self.apply(second, change(second))
        self.apply(second, change(second, title='重复重试不应创建'))
        self.assertEqual(len(self.app.state()['tasks']), 1)
        self.assertEqual(self.task()['evidence'], [first, second])

    def test_different_owners_and_patients_not_merged(self):
        mid = self.message(); self.apply(mid, change(mid), change(mid, owner='patient'))
        other = self.message(patient=2); self.apply(other, change(other), patient=2)
        self.assertEqual(len(self.app.state()['tasks']), 3)
        third = self.message(patient=2)
        with self.assertRaises(ModelError): self.apply(third, change(third, task_id=self.app.state()['tasks'][-1]['id']), patient=2)

    def test_rejected_old_evidence_cannot_resurface(self):
        mid = self.message('我已核对并回复。'); self.apply(mid, change(mid, signal='possible'))
        task = self.task(); self.app.edit_task(task['id'], 'reject')
        self.assertEqual(self.task()['dismissed'], [mid])
        self.app.apply_analysis(1, mid, {'changes': [change(mid, signal='possible', task_id=task['id'])]})
        self.assertEqual(self.task()['status'], 'pending')
        later = self.message('谢谢'); c = change(later, signal='possible', task_id=task['id']); c['evidence']=[mid]
        with self.assertRaises(ModelError): self.apply(later, c)
        self.assertEqual(self.task()['status'], 'pending')
        self.apply(later)

    def test_partial_and_contradiction_do_not_complete(self):
        mid = self.message(); self.apply(mid, change(mid, signal='possible')); task = self.task()
        second = self.message('已核对，但还没回复。'); c = change(second, task_id=task['id'], signal='partial'); c['remaining']='回复结果'
        self.apply(second, c)
        self.assertEqual(self.task()['status'], 'pending'); self.assertEqual(self.task()['remaining'], '回复结果')
        self.app.edit_task(task['id'], 'confirm')
        third = self.message('刚才说错了，还没有核对。'); self.apply(third, change(third, task_id=task['id'], signal='contradiction'))
        self.assertEqual(self.task()['status'], 'completed'); self.assertEqual(self.task()['signal'], 'contradiction')
        self.app.edit_task(task['id'], 'reopen'); self.assertEqual(self.task()['status'], 'pending')

    def test_edit_cancel_and_reopen(self):
        mid = self.message(); self.apply(mid, change(mid)); task = self.task()
        self.app.edit_task(task['id'], 'edit', {'title':'手动标题','due':'下周一','owner':'caregiver'})
        second=self.message(); self.apply(second, change(second, task_id=task['id']))
        self.assertEqual(self.task()['title'], '手动标题'); self.assertEqual(self.task()['due'], '下周一')
        self.app.edit_task(task['id'], 'cancel')
        third=self.message(); self.apply(third, change(third, task_id=task['id'], signal='possible'))
        self.assertEqual(self.task()['status'], 'cancelled')
        self.app.edit_task(task['id'], 'reopen'); self.assertEqual(self.task()['status'], 'pending')

    def test_retry_reply_stage_does_not_repeat_user_or_analysis(self):
        self.app.model = FakeModel([{'changes': []}, ModelError('offline'), '好的，我明天发。', {'changes': []}])
        job = self.app.submit(1, '请把记录发给我。', request_id='stable-request-id'); self.app.run_job(job['id'])
        snapshot = self.app.state()
        self.assertEqual(snapshot['jobs'][0]['stage'], 'reply'); self.assertEqual(snapshot['jobs'][0]['status'], 'failed')
        self.assertEqual(len(snapshot['messages']), 1)
        self.assertEqual(self.app.submit(1, '请把记录发给我。', request_id='stable-request-id')['id'], job['id'])
        self.app.retry(job['id']); self.app.run_job(job['id'])
        self.assertEqual(len(self.app.state()['messages']), 2); self.assertEqual(self.app.state()['jobs'], [])
        self.assertEqual(len(self.app.model.calls), 4)

    def test_retry_patient_analysis_does_not_generate_reply_again(self):
        self.app.model = FakeModel([{'changes': []}, '我明天发。', ModelError('bad JSON'), {'changes': []}])
        job=self.app.submit(1,'请发记录'); self.app.run_job(job['id'])
        self.assertEqual(self.app.state()['jobs'][0]['stage'], 'analyze_patient')
        self.app.retry(job['id']); self.app.run_job(job['id'])
        self.assertEqual(len(self.app.state()['messages']), 2); self.assertEqual(len(self.app.model.calls), 4)

    def test_prompt_isolation(self):
        self.app.model=FakeModel([{'changes': []}, '请问我应该如何整理记录？', {'changes': []}])
        job=self.app.submit(1, '您好'); self.app.run_job(job['id'])
        for messages,schema in self.app.model.calls:
            if schema:
                self.assertNotIn('上周有两天没记', json.dumps(messages, ensure_ascii=False))
                self.assertNotIn('陈明远', json.dumps(messages, ensure_ascii=False))
        self.assertIn('上周有两天没记', json.dumps(self.app.model.calls[1][0], ensure_ascii=False))

    def test_restart_persistence_and_interrupted_job(self):
        mid=self.message(); self.apply(mid, change(mid)); job=self.app.submit(2, '您好')
        with self.app.db() as con: con.execute("UPDATE jobs SET status='running' WHERE id=?", (job['id'],))
        restarted=CareApp(self.path, FakeModel())
        self.assertEqual(len(restarted.state()['tasks']), 1); self.assertEqual(len(restarted.state()['messages']), 2)
        self.assertEqual(restarted.state()['jobs'][0]['status'], 'failed')

    def test_block_same_patient_allow_other_and_reset_confirmation(self):
        self.app.submit(1, '您好')
        with self.assertRaises(ValueError): self.app.submit(1, '再发')
        self.app.submit(2, '您好')
        with self.assertRaises(ValueError): self.app.reset('重新开始')
        with self.app.db() as con: con.execute("UPDATE jobs SET status='failed'")
        with self.assertRaises(ValueError): self.app.reset('')
        self.app.reset('重新开始')
        self.assertEqual(self.app.state()['messages'], []); self.assertEqual(self.app.state()['jobs'], [])

if __name__ == '__main__': unittest.main()
