"""Choose a development relevance threshold from all labeled clip scores.

Uses the same labels as evaluate.py. This is a clip-level F1 choice before
deduplication, not held-out recall@5. Always evaluate on separate footage later.
"""
import argparse
import json
from pathlib import Path

from app.ai.gemini_embedding import GeminiEmbeddingAdapter
from app.config import Settings
from app.service import normalized
from app.store import Store
from evaluate import overlap


def choose_threshold(samples):
    if not samples or not any(s['relevant'] for s in samples) or all(s['relevant'] for s in samples):
        raise ValueError('Calibration needs both relevant and unrelated clip/query examples')
    choices = []
    for threshold in sorted({s['score'] for s in samples}):
        tp = sum(s['relevant'] and s['score'] >= threshold for s in samples)
        fp = sum(not s['relevant'] and s['score'] >= threshold for s in samples)
        fn = sum(s['relevant'] and s['score'] < threshold for s in samples)
        f1 = 2*tp/(2*tp+fp+fn) if tp else 0
        choices.append((f1, -fp, threshold, tp, fp, fn))
    f1, _, threshold, tp, fp, fn = max(choices)
    return {'relevance_threshold':threshold,'development_clip_f1':f1,'true_positive_clips':tp,'false_positive_clips':fp,'false_negative_clips':fn,'sample_count':len(samples),'note':'Development threshold; validate held-out recall@5 and false positives separately.'}


def calibrate(dataset, adapter, settings):
    store = Store(settings.data_dir)
    samples = []
    for query in dataset['queries']:
        vector = normalized(adapter.embed_text(query['query']))
        with store.transaction() as db:
            rows = list(db.execute('SELECT * FROM clips WHERE video_id IN (%s)' % ','.join('?' for _ in query['video_ids']),query['video_ids']))
        if not rows:
            raise ValueError('No published index for a development query')
        for row in rows:
            if row['revision'] != adapter.fingerprint:
                raise ValueError('Index fingerprint differs from calibration model')
            clip, embedding = json.loads(row['body']),json.loads(row['vector'])
            if len(vector) != len(embedding):
                raise ValueError('Index dimension mismatch')
            score = max(-1,min(1,sum(a*b for a,b in zip(vector,embedding))))
            samples.append({'score':score,'relevant':any(overlap(clip,target) for target in query['expected'])})
    return choose_threshold(samples)


if __name__ == '__main__':
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument('labels',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    settings = Settings()
    adapter = GeminiEmbeddingAdapter(model=os.getenv('GEMINI_EMBEDDING_MODEL','gemini-embedding-2'))
    adapter.load()
    args.output.write_text(json.dumps(calibrate(json.loads(args.labels.read_text()),adapter,settings),indent=2,allow_nan=False)+'\n')
