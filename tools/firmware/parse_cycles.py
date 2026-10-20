import json, re

fruits = []
with open('C:/Users/kpvlo/.gemini/antigravity/brain/59e43f35-4e8d-44c4-b58e-bb9d6f44e448/.system_generated/logs/transcript.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        try:
            d = json.loads(line)
            c = d.get('content', '')
            if '0xf1d1a600' in c:
                m_f = re.search(r'"fruit":\s*(-?\d+)', c)
                m_c = re.search(r'"tcs_c":\s*(\d+)', c)
                m_conf = re.search(r'"fruit_conf_pm":\s*(\d+)', c)
                m_pr = re.search(r'"fruit_present":\s*(\d+)', c)
                if m_f and m_c and m_conf and m_pr:
                    fr = int(m_f.group(1))
                    tc = int(m_c.group(1))
                    cf = int(m_conf.group(1))
                    pr = int(m_pr.group(1))
                    if pr == 1 and fr >= 0:
                        fruits.append((fr, cf, tc))
        except:
            pass

print(f"Total present fruit cycles: {len(fruits)}")
for fr, cf, tc in fruits[-25:]:
    print(f"fruit={fr}, conf={cf}, tcs_c={tc}")
