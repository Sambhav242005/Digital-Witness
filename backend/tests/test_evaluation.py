import importlib.util
from pathlib import Path
import sys
import pytest

scripts = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(scripts))
from calibrate import choose_threshold
from evaluate import overlap


def test_development_threshold_balances_relevant_and_unrelated_clips():
    samples = [{'score':.9,'relevant':True},{'score':.8,'relevant':True},{'score':.6,'relevant':False},{'score':.1,'relevant':False}]
    outcome = choose_threshold(samples)
    assert outcome['relevance_threshold'] == .8
    assert outcome['development_clip_f1'] == 1
    assert outcome['false_positive_clips'] == 0


@pytest.mark.parametrize('samples',[[],[{'score':.8,'relevant':True}],[{'score':.8,'relevant':False}]])
def test_threshold_requires_positive_and_negative_evaluation(samples):
    with pytest.raises(ValueError):
        choose_threshold(samples)


def test_overlap_uses_selected_video_and_half_open_time():
    a = dict(video_id='a',start_sec=0,end_sec=8)
    assert overlap(a,dict(video_id='a',start_sec=7,end_sec=9))
    assert not overlap(a,dict(video_id='a',start_sec=8,end_sec=9))
    assert not overlap(a,dict(video_id='b',start_sec=0,end_sec=8))
