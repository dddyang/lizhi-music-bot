import json, re

with open(r'C:\Users\LIBI\.gemini\antigravity\brain\e23e1907-8532-4f3d-8307-10830338f0e3\.system_generated\logs\transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        if 'jsdelivr' in line or 'Nayacco' in line or 'turkyden' in line:
            obj = json.loads(line)
            content = str(obj.get('content', '')) + str(obj.get('tool_calls', ''))
            matches = re.findall(r'https?://[^\s"\'\\]+', content)
            for m in set(matches):
                if any(k in m for k in ['jsdelivr', 'github', 'Nayacco', 'turkyden']):
                    print(m)
