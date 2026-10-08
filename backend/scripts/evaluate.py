"""Measure retrieval from labeled real footage; no inferred accuracy claim.

Input: {"queries":[{"query":"...", "video_ids":["..."],
"expected":[{"video_id":"...","start_sec":1,"end_sec":3}]}]}
Empty expected marks unrelated queries. Run against already indexed footage.
"""
import argparse
import json
import time
from pathlib import Path
import httpx


def overlap(a, b):
    return a['video_id'] == b['video_id'] and a['start_sec'] < b['end_sec'] and b['start_sec'] < a['end_sec']


def evaluate(base_url, dataset, timeout=1800):
    measurements = []
    with httpx.Client(base_url=base_url, timeout=60) as client:
        for query in dataset['queries']:
            started = time.perf_counter()
            response = client.post('/api/v1/searches',json={'query':query['query'],'video_ids':query['video_ids'],'limit':5})
            response.raise_for_status()
            key = response.json()['data']['search_id']
            deadline = time.monotonic()+timeout
            while True:
                response = client.get('/api/v1/searches/'+key)
                response.raise_for_status()
                search = response.json()['data']
                if search['status'] in ('failed','succeeded'):
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Search did not finish within evaluation timeout')
                time.sleep(2)
            if search['status'] != 'succeeded':
                raise RuntimeError('Search failed: '+search['error']['code'])
            expected, results = query['expected'], search['results']
            matched = sum(any(overlap(target,result) for result in results) for target in expected)
            false_positives = sum(not any(overlap(result,target) for target in expected) for result in results)
            measurements.append({'query':query['query'],'latency_sec':time.perf_counter()-started,'expected_count':len(expected),'matched_count':matched,'recall_at_5':matched/len(expected) if expected else None,'false_positive_candidates':false_positives,'verification_statuses':[r['verification']['status'] for r in results],'scores':[r['retrieval_score'] for r in results], 'warnings':search['warnings']})
    expected_count = sum(m['expected_count'] for m in measurements)
    return {'queries':measurements,'recall_at_5':sum(m['matched_count'] for m in measurements)/expected_count if expected_count else None,'false_positive_candidates':sum(m['false_positive_candidates'] for m in measurements),'mean_latency_sec':sum(m['latency_sec'] for m in measurements)/len(measurements) if measurements else None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('labels',type=Path)
    parser.add_argument('--base-url',default='http://localhost:8000')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(evaluate(args.base_url,json.loads(args.labels.read_text())),indent=2,allow_nan=False)+'\n')
