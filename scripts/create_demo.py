"""Synthetic-only opt-in demo. Never reads a user's Codex sessions."""
from pathlib import Path
import argparse,json,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.fixtures import meta,user,write

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--append',action='store_true');args=parser.parse_args()
    base=ROOT/'.tmp/demo';logs=base/'logs';project=base/'project'
    logs.mkdir(parents=True,exist_ok=True);project.mkdir(parents=True,exist_ok=True)
    config={'sessions_root':str(logs),'runtime':str(base/'runtime'),
            'allowed_projects':[str(project)],'publication_root':str(base/'publications'),
            'budget':1000,'encoding':'cl100k_base','reserves':{}}
    (base/'config.json').write_bytes((json.dumps(config,indent=2)+'\n').encode('utf-8'))
    if args.append:
        cid='demo-'+str(time.time_ns())
        write(logs/(cid+'.jsonl'),[meta(cid,project),user('u','This is synthetic demo text. No real chat was read.')])
        print('Created synthetic chat',cid)
    else:print('Config ready. Start the window, then run this script with --append.')
