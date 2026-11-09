import json

def meta(cid, project, source='cli'):
    return {'type': 'session_meta', 'payload': {'id': cid, 'cwd': str(project), 'source': source}}

def user(mid, text, turn='t1', provenance='user'):
    return {'type': 'response_item', 'payload': {'type': 'message', 'id': mid, 'role': 'user',
        'content': [{'type': 'input_text', 'text': text}],
        'internal_chat_message_metadata_passthrough': {'turn_id': turn,
          'content_item_kinds': ['user.text' if provenance == 'user' else 'host.context'],
          'content_item_metadata': [{'provenance': {'type': provenance}}]}}}

def assistant(mid, text, turn='t1', channel='final'):
    return {'type': 'response_item', 'payload': {'type': 'message', 'id': mid,
        'role': 'assistant', 'turn_id': turn, 'channel': channel,
        'content': [{'type': 'output_text', 'text': text}]}}

def completed(mid, text, turn='t1', kind='AgentMessage', **extra):
    return {'type': 'event_msg', 'payload': {'type': 'item_completed', 'turn_id': turn,
        'item': {'type': kind, 'id': mid, 'content': [{'type': 'text', 'text': text}], **extra}}}

def write(path, records, append=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a' if append else 'w', encoding='utf-8', newline='\n') as stream:
        for i, record in enumerate(records):
            record = dict(record)
            record.setdefault('timestamp', f'2026-11-03T00:00:{i:02d}Z')
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')

