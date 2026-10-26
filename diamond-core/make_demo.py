"""Reproduce the non-sensitive, assistant-assisted demonstration; no live model call."""
import json
from pathlib import Path
from discovery_review import prepare, search

source = {
 'kind':'founder_message', 'ref':'founder:activation-mission:2026-10-18',
 'title':'Diamond Core Activation Mission — selected founder-authored excerpts',
 'creator':'Founders, supplied in current conversation', 'published_at':None,
 'captured_at':'2026-10-18T20:47:38+00:00',
 'access_basis':'Founder supplied text; authorized by activation mission Phase 6',
 'content':"The goal isn't for Diamond Core to know everything. It's for us to become better at discovering what we don't yet know.\nStore hypotheses as hypotheses, not facts.\nPreserve dissenting interpretations and update conclusions when new evidence appears.\nDo not automatically promote new material into Diamond Core's canonical knowledge without owner approval.\nTruth constrains what Core may claim. It should not constrain what Core may wonder about."
}
analysis = {
 'ideas':[
  {'statement':'The founders prioritize improving discovery over accumulating everything.',
   'kind':'founder_observation', 'evidence_state':'OWNER-CONFIRMED',
   'excerpt':"It's for us to become better at discovering what we don't yet know.", 'locator':'Mission guiding principle'},
  {'statement':'The founders require hypothesis labels and preservation of dissent.',
   'kind':'founder_observation', 'evidence_state':'OWNER-CONFIRMED',
   'excerpt':'Store hypotheses as hypotheses, not facts.', 'locator':'Phase 4'},
  {'statement':'Approval to examine a source does not approve its conclusions as canonical knowledge.',
   'kind':'provisional_interpretation', 'evidence_state':'IDEA',
   'excerpt':"Do not automatically promote new material into Diamond Core's canonical knowledge without owner approval.", 'locator':'Phase 5'}
 ],
 'discovery':{
  'connection':'Curated learning can use the same separation between evidence and proposed connections that Core already uses for Universe Census staging; this resembles the separation of observations and hypotheses in an experiment log.',
  'why_it_matters':'A valuable interview could raise a question for a creative project without being forced into a scored commercial opportunity or promoted into fact.',
  'support':'The mission explicitly separates hypotheses from facts. Snapshot PROJECT_STATUS.md describes Census Batch 002 as noncanonical and separates historical relationships from proposed connections. That supports reuse of the review pattern, not proof that it improves discovery.',
  'challenge':'An additional review step may create a backlog instead of learning. Some ideas need only a short note; forcing every source into a project could distort it. No observed outcome yet supports a quality improvement.',
  'next_step':'With one confirmed podcast link, prepare one source-grounded review and ask the founders whether it yields a useful new question and a meaningful counterargument. Record that outcome without canonical promotion.'
 },
 'projects':['Diamond Core','DMIO'],
 'dissent':['A detailed review format may cost more attention than the connection is worth; allow low-value intake to stop after triage.'],
 'questions':['Does preserving a counterargument change which ideas the founders choose to test?', 'Can curiosity remain useful without an immediate business application?'],
 'context_sources':[{'ref':'archive:84912ca6-e010-48e0-8d45-4406491973c0.zip/diamond-core/PROJECT_STATUS.md',
                     'locator':'Universe Census Batch 002', 'freshness':'Historical snapshot; not live state'}]
}
envelope = {'source':source,
 'approval':{'source_ref':source['ref'], 'scope':'review_only', 'instruction_ref':'Current activation mission Phase 6: test using a non-sensitive source'},
 'analysis':analysis, 'analyst':'ChatGPT assistant, source-assisted review; not a live Core/Gemini run',
 'reviewed_at':'2026-10-18T21:00:00+00:00'}

def run(destination):
 destination.mkdir(exist_ok=True)
 # Create-only outputs avoid accidental replacement of prior demonstrations.
 packet,status = prepare(**envelope)
 updated = json.loads(json.dumps(envelope))
 updated['analysis']['questions'].append('What is the minimum review that preserves a useful challenge?')
 second,_ = prepare(**updated,previous=packet)
 for name,data in [('demo_input.json',envelope),('discovery_history.json',[packet,second])]:
  with (destination/name).open('x',encoding='utf-8') as f: json.dump(data,f,indent=2,ensure_ascii=False)
 duplicate = prepare(**envelope,previous=packet)[1]
 hits=search(json.loads((destination/'discovery_history.json').read_text()),'counterargument')
 print(json.dumps({'first_intake':status,'repeat_intake':duplicate,'revisions_saved':2,
                   'retrieved_revisions':len(hits),'canonical':False}))

if __name__=='__main__':
 run(Path('demo'))
