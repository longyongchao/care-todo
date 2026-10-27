import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ollama_client import Ollama, ModelError, MODEL

class ModelTests(unittest.TestCase):
    def test_missing_model(self):
        model=Ollama(); model.request=Mock(return_value={'models': []})
        health=model.health()
        self.assertFalse(health['ok']); self.assertIn(MODEL,health['message'])
    def test_offline_preserves_clear_error(self):
        model=Ollama(); model.opener.open=Mock(side_effect=urllib.error.URLError('offline'))
        health=model.health()
        self.assertFalse(health['ok']); self.assertIn('ollama serve',health['message'])
    def test_remote_model_refused(self):
        model=Ollama(); model.request=Mock(return_value={'models':[{'name':MODEL,'remote_host':'https://example.invalid'}]})
        self.assertFalse(model.health()['ok'])
    def test_invalid_json_and_truncated_response(self):
        for response in ({'message':{'content':'not json'}}, {'message':{'content':'{}'},'done_reason':'length'}):
            model=Ollama(); model.health=Mock(return_value={'ok':True}); model.request=Mock(return_value=response)
            with self.assertRaises(ModelError): model.chat([], {'type':'object'})
    def test_local_request_contract(self):
        model=Ollama(); model.health=Mock(return_value={'ok':True}); model.request=Mock(return_value={'message':{'content':'{"changes":[]}'}})
        self.assertEqual(model.chat([],{'type':'object'}),{'changes':[]})
        path,payload=model.request.call_args.args
        self.assertEqual(path,'/api/chat'); self.assertEqual(payload['model'],MODEL)
        self.assertFalse(payload['stream']); self.assertFalse(payload['think'])

if __name__=='__main__': unittest.main()
