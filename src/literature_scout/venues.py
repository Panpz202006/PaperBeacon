"""Conservative venue validation from bibliographic METADATA, not paper claims."""
from __future__ import annotations
from .models import normalize_text, Paper

# Extend here or add config.ven ue_aliases in a configuration file.
ALIASES = {
    'CVPR': ['CVPR', 'IEEE/CVF Conference on Computer Vision and Pattern Recognition',
             'Proceedings of the IEEE CVF Conference on Computer Vision and Pattern Recognition'],
    'ICCV': ['ICCV', 'IEEE/CVF International Conference on Computer Vision'],
    'ECCV': ['ECCV', 'European Conference on Computer Vision', 'Computer Vision ECCV'],
    'NeurIPS': ['NeurIPS', 'NIPS', 'Advances in Neural Information Processing Systems',
               'Neural Information Processing Systems'],
    'ICLR': ['ICLR', 'International Conference on Learning Representations'],
    'ICML': ['ICML', 'International Conference on Machine Learning'],
    'AAAI': ['AAAI', 'AAAI Conference on Artificial Intelligence', 'Proceedings of the AAAI Conference on Artificial Intelligence'],
    'IJCAI': ['IJCAI', 'International Joint Conference on Artificial Intelligence'],
    'MICCAI': ['MICCAI', 'Medical Image Computing and Computer Assisted Intervention',
              'Medical Image Computing and Computer-Assisted Intervention'],
    'BIBM': ['BIBM', 'IEEE International Conference on Bioinformatics and Biomedicine'],
    'IEEE TMI': ['IEEE TMI', 'IEEE Transactions on Medical Imaging', 'Transactions on Medical Imaging'],
    'Medical Image Analysis': ['Medical Image Analysis', 'Med Image Anal'],
    'IEEE TBME': ['IEEE TBME', 'IEEE Transactions on Biomedical Engineering'],
    'TNNLS': ['IEEE Transactions on Neural Networks and Learning Systems', 'TNNLS'],
    'TPAMI': ['IEEE Transactions on Pattern Analysis and Machine Intelligence', 'TPAMI'],
    'IEEE TIP': ['IEEE Transactions on Image Processing', 'TIP'],
}

# Selective *known* proceedings variants; custom venues require exact alias match.
PROCEEDINGS_NAMES = {'CVPR', 'ICCV', 'ECCV', 'NeurIPS', 'ICLR', 'ICML', 'AAAI', 'IJCAI', 'MICCAI', 'BIBM'}
WORKSHOP_TERMS = {'workshop', 'workshops', 'companion', 'poster abstracts'}


def match_venue(raw: str, desired: list[str], custom_aliases: dict[str, list[str]] | None = None) -> str:
    val = normalize_text(raw)
    if not val or val in {'arxiv', 'arxiv preprint', 'repository'}:
        return ''
    alias_map = dict(ALIASES)
    alias_map.update(custom_aliases or {})
    # Reject workshops as conferences. Workshop eligibility can be configured
    # separately under its exact, explicit venue name.
    for canonical in desired:
        aliases = alias_map.get(canonical, [canonical])
        for alias in aliases:
            norm = normalize_text(alias)
            if not norm:
                continue
            matched = val == norm
            # Leading publication year, e.g. "2025 IEEE/CVF Conference..."
            if canonical in PROCEEDINGS_NAMES and len(val) > 5 and val[:4].isdigit() and val[4] == ' ':
                matched = matched or (val[5:] == norm)
            # Recognize proceedings suffix with year only; not substring-only matches.
            if canonical in PROCEEDINGS_NAMES and val.startswith(norm + ' '):
                tail = val[len(norm):].strip()
                if tail.isdigit() and len(tail) == 4:
                    matched = True
                elif canonical == 'MICCAI' and tail.startswith('miccai '):
                    matched = True
            if matched and canonical in PROCEEDINGS_NAMES:
                if set(val.split()) & WORKSHOP_TERMS:
                    matched = False
            if matched:
                return canonical
        # Some long proceedings titles include exact subtitle and year;
        # use explicit alias configuration rather than guessing.
    return ''


def gate(paper: Paper, *, venues: list[str], include_arxiv: bool,
         aliases: dict[str, list[str]] | None = None) -> Paper | None:
    found = match_venue(paper.venue_raw, venues, aliases)
    if found:
        paper.venue_canonical = found
        paper.venue_evidence = 'metadata'
        return paper
    if include_arxiv and paper.arxiv_id:
        paper.venue_canonical = 'arXiv'
        paper.venue_evidence = 'preprint'
        return paper
    if include_arxiv and paper.venue_raw.casefold().strip() in {'arxiv', 'arxiv preprint'}:
        paper.venue_canonical = 'arXiv'
        paper.venue_evidence = 'preprint'
        return paper
    return None
