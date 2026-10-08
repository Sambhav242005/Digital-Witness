"""Allowlisted visual questions, quality gates and conservative aggregation."""
import math
import re

CHECKS = {
    "bag_present": "Is a bag visibly present in this image?",
    "person_carrying_bag": "Is a person visibly carrying a bag?",
}


def checks_for_query(query):
    text = query.lower()
    # Temporal, identity, ownership and negated claims cannot be supported by
    # a positive sampled-image question. Keep semantic retrieval valid.
    if re.search(r"\b(no|not|without|never|abandon\w*|unattended|owner\w*|steal\w*|stole|identity|enter\w*|exit\w*|depart\w*|retriev\w*)\b|\b(same person|left behind|leav\w*.*bag|every time)\b", text):
        return []
    if not re.search(r"\b(bag|bags|backpack|backpacks|handbag|suitcase)\b", text):
        return []
    key = "person_carrying_bag" if re.search(r"\b(carry\w*|holding)\b", text) else "bag_present"
    return [{"check_id": key, "question": CHECKS[key]}]


def image_quality(image_path, min_size=64, min_contrast=8.0, min_edge_variance=12.0):
    """Heuristic gate, not a calibrated readability score; thresholds need footage validation."""
    try:
        from PIL import Image, ImageFilter, ImageStat
        with Image.open(image_path) as image:
            if min(image.size) < min_size:
                return "poor"
            gray = image.convert("L")
            gray.thumbnail((512, 512))
            contrast = ImageStat.Stat(gray).stddev[0]
            # Crop filter borders, which otherwise give a constant image artificial edges.
            edges = gray.filter(ImageFilter.FIND_EDGES).crop((1, 1, gray.width-1, gray.height-1))
            sharpness = ImageStat.Stat(edges).var[0]
            return "usable" if contrast >= min_contrast and sharpness >= min_edge_variance else "poor"
    except (OSError, ValueError):
        return "poor"


def answer_for_probability(probability, yes_threshold=0.8, no_threshold=0.2):
    if not 0 <= no_threshold < yes_threshold <= 1:
        raise ValueError("Invalid verification thresholds")
    if probability is None:
        return "uncertain"
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("Invalid probability")
    return "yes" if probability >= yes_threshold else "no" if probability <= no_threshold else "uncertain"


def aggregate_checks(evidence):
    checks = [check for frame in evidence if frame["quality"] == "usable" for check in frame["checks"]]
    answers = {check["answer"] for check in checks}
    if not checks:
        status, reason = "uncertain", "No readable sampled frame supports a visual decision."
    elif answers == {"yes"}:
        status, reason = "supported", "Readable sampled frames support the declared visual check only; temporal actions and entrance proximity are unverified."
    elif answers == {"no"}:
        status, reason = "contradicted", "The declared visual check was negative in readable sampled frames; this does not establish absence throughout the recording."
    else:
        status, reason = "uncertain", "Sampled visual checks are mixed or uncertain."
    return {"status": status, "basis": "frame_checks", "reason": reason}
