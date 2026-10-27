"""Minimal decoder for SvelteKit __data.json (devalue 'stringify' format), used for eduskunta.fi asia pages.
Each node's data is a flat array; values refer to other entries by index (-1 = undefined).
Usage as a script: python3 devalue.py <file.json> -> prints JSON of all nodes' data."""
import json, sys

UNDEF = None
def unflatten(values):
    cache = {}
    def hyd(i):
        if i == -1: return None      # undefined
        if i == -2: return float('nan')
        if i == -3: return float('inf')
        if i == -4: return float('-inf')
        if i == -5: return -0.0
        if i == -6: return None      # hole
        if i in cache: return cache[i]
        v = values[i]
        if isinstance(v, (int, float, str, bool)) or v is None:
            cache[i] = v; return v
        if isinstance(v, list):
            if v and isinstance(v[0], str):
                t = v[0]
                if t == 'Date': cache[i] = v[1]; return v[1]
                if t == 'Set': out=[]; cache[i]=out; out.extend(hyd(x) for x in v[1:]); return out
                if t == 'Map': out={}; cache[i]=out; [out.__setitem__(hyd(v[k]), hyd(v[k+1])) for k in range(1,len(v),2)]; return out
                if t == 'Object': cache[i] = v[1]; return v[1]
                if t == 'null': out={}; cache[i]=out; [out.__setitem__(v[k], hyd(v[k+1])) for k in range(1,len(v),2)]; return out
                if t in ('RegExp','BigInt'): cache[i]=v[1]; return v[1]
            out = []; cache[i] = out
            out.extend(hyd(x) for x in v); return out
        if isinstance(v, dict):
            out = {}; cache[i] = out
            for k, x in v.items(): out[k] = hyd(x)
            return out
        return v
    return hyd(0)

def decode(doc):
    res = []
    for n in doc.get('nodes') or []:
        if n and n.get('type') == 'data':
            res.append(unflatten(n['data']))
        else:
            res.append(None)
    return res

if __name__ == '__main__':
    doc = json.load(open(sys.argv[1]))
    print(json.dumps(decode(doc), ensure_ascii=False, indent=1))
