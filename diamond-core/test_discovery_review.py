import copy
import json
import tempfile
import unittest
from pathlib import Path
from discovery_review import prepare, search, build_prompt, validate_packet
from make_demo import envelope, run

class ReviewTests(unittest.TestCase):
 def test_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   run(Path(d))
   data=json.loads((Path(d)/'discovery_history.json').read_text())
   self.assertEqual(len(search(data,'counterargument')),2)
   self.assertEqual(data[1]['previous_packet_hash'],data[0]['packet_hash'])
   self.assertFalse(data[0]['canonical'])
 def test_permission_required(self):
  e=copy.deepcopy(envelope); e['approval']['source_ref']='different'
  with self.assertRaises(ValueError): prepare(**e)
 def test_no_false_promotion(self):
  e=copy.deepcopy(envelope); e['analysis']['ideas'][0]['evidence_state']='VERIFIED'
  with self.assertRaises(ValueError): prepare(**e)
 def test_no_invented_quote(self):
  e=copy.deepcopy(envelope); e['analysis']['ideas'][0]['excerpt']='invented'
  with self.assertRaises(ValueError): prepare(**e)
 def test_challenge_required(self):
  e=copy.deepcopy(envelope); e['analysis']['discovery']['challenge']=''
  with self.assertRaises(ValueError): prepare(**e)
 def test_duplicate(self):
  p,_=prepare(**envelope)
  self.assertEqual(prepare(**envelope,previous=p),(p,'duplicate'))
 def test_changed_source_revision(self):
  p,_=prepare(**envelope); e=copy.deepcopy(envelope); e['source']['content']+=' New note.'
  new,status=prepare(**e,previous=p)
  self.assertEqual((new['revision'],status),(2,'new_revision'))
  self.assertEqual(p['revision'],1)
 def test_tampered_packet(self):
  p,_=prepare(**envelope); p['analysis']['dissent']=[]
  with self.assertRaises(ValueError): validate_packet(p)
 def test_email_requires_selection(self):
  e=copy.deepcopy(envelope); e['source']['kind']='email'
  with self.assertRaises(ValueError): prepare(**e)
 def test_unknown_project(self):
  e=copy.deepcopy(envelope); e['analysis']['projects']=['Invented business']
  with self.assertRaises(ValueError): prepare(**e)
 def test_prompt(self):
  self.assertIn('untrusted data',build_prompt(envelope['source'],envelope['approval']))
 def test_timestamp(self):
  e=copy.deepcopy(envelope); e['reviewed_at']='2026-10-18T21:00:00'
  with self.assertRaises(ValueError): prepare(**e)

if __name__=='__main__': unittest.main()
