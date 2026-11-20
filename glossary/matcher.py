"""Transkript metninde alan terimlerini bulur.

Bir terim kelimesi, transkriptteki bir kelimeyle şu durumlarda eşleşir:
  1. Normalize edilmiş biçimler aynıysa                ("yığın" = "yığın")
  2. zeyrek kök adayları terimin biçimlerini içeriyorsa  ("ağaçlarında" -> "ağaç")
  3. Terim biçimi önek, kalan kısım Türkçe çekim ekiyse  ("algoritma|nın", "önbelleğ|e")
  4. rapidfuzz benzerliği eşik üstündeyse (yazım/tanıma hataları; "algoritim|anın")
Çok kelimeli terimler ("ikili arama ağacı") ardışık kelimelerle eşleştirilir;
çakışmada daha uzun eşleşme kazanır.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from functools import lru_cache

from django.conf import settings
from rapidfuzz import fuzz

logger = logging.getLogger("glossary.matcher")

# --- Türkçe metin yardımcıları ---------------------------------------------

_CIRCUMFLEX = str.maketrans({"â": "a", "î": "i", "û": "u", "Â": "a", "Î": "i", "Û": "u"})
_TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)
_SOFTEN = {"k": "ğ", "ç": "c", "t": "d", "p": "b"}
_HARDEN = {"ğ": "k", "c": "ç", "d": "t", "b": "p"}
_VOWELS = "aeıioöuü"

# Ad çekim ekleri zinciri (çoğul, iyelik, hâl, -ki, ek-fiil). Bilerek basit tutuldu.
_SUFFIX_PART = (
    r"l[ae]r|"
    r"[ıiuü]m[ıiuü]z|[ıiuü]n[ıiuü]z|m[ıiuü]z|n[ıiuü]z|"
    r"n?[ıiuü]n|s?[ıiuü]|y?[ıiuü]|n[ıiuü]|"
    r"n?[dt][ae]n|n?[dt][ae]|y?[ae]|n[ae]|"
    r"y?l[ae]|k[iü]|[dt][ıiuü]r|"
    r"[ıiuü]m"
)
# Not: tek başına "n"/"m" eki bilerek yok ("dizin" -> "dizi" gibi yanlış eşleşmeleri önler).
SUFFIX_RE = re.compile(rf"(?:{_SUFFIX_PART}){{1,4}}")
MAX_SUFFIX_LEN = 9


def tr_lower(text: str) -> str:
    return text.replace("I", "ı").replace("İ", "i").translate(_CIRCUMFLEX).lower().replace("̇", "")


def normalize_token(token: str) -> str:
    return tr_lower(token).replace("'", "").replace("’", "")


@dataclass
class Token:
    norm: str
    start: int
    end: int
    lemmas: frozenset[str] = field(default_factory=frozenset)


def tokenize(text: str) -> list[Token]:
    return [Token(normalize_token(m.group()), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]


# --- zeyrek ----------------------------------------------------------------

_analyzer = None
_analyzer_lock = threading.Lock()
_analyzer_failed = False


def _get_analyzer():
    global _analyzer, _analyzer_failed
    if _analyzer is not None or _analyzer_failed or not settings.TERM_MATCHING["USE_ZEYREK"]:
        return _analyzer
    with _analyzer_lock:
        if _analyzer is None and not _analyzer_failed:
            try:
                import zeyrek

                logging.getLogger("zeyrek").setLevel(logging.ERROR)
                _analyzer = zeyrek.MorphAnalyzer()
                logger.info("zeyrek biçimbilim çözümleyicisi yüklendi")
            except Exception:  # pragma: no cover
                logger.exception("zeyrek yüklenemedi; kök bulma devre dışı")
                _analyzer_failed = True
    return _analyzer


@lru_cache(maxsize=50_000)
def lemmas(word: str) -> frozenset[str]:
    """Kelimenin olası kökleri (küçük harf). zeyrek yoksa boş küme."""
    analyzer = _get_analyzer()
    if analyzer is None or not word or not word.isalpha():
        return frozenset()
    try:
        # lemmatize() nltk 'punkt' verisi istediği için tek kelimeyi doğrudan çözümlüyoruz
        parses = analyzer._parse(word)
    except Exception:
        return frozenset()
    return frozenset(tr_lower(p.dict_item.lemma) for p in parses if p is not None and p.dict_item)


def warm_up():
    """Ağır modelleri önceden yükler (sunucu açılışında/ilk oturumda çağrılır)."""
    lemmas("algoritmanın")


# --- terim kalıpları ------------------------------------------------------------


def _forms_for(word: str, compound_head: bool = False) -> frozenset[str]:
    """Bir terim kelimesinin eşleşmede kullanılacak biçimleri.

    compound_head: çok kelimeli terimin son kelimesi mi (iyelik eki taşıyabilir)?
    """
    forms = {word}
    if len(word) >= 3 and word[-1] in _SOFTEN:  # önbellek -> önbelleğ(e)
        forms.add(word[:-1] + _SOFTEN[word[-1]])
    # Tamlama iyelik eki: ağacı -> ağaç, parçacığı -> parçacık, karmaşıklığı -> karmaşıklık
    # (yalnızca tamlamalarda; tek kelimelik "dizi" -> "diz" yapılmaz)
    word_lemmas = lemmas(word)
    if compound_head and len(word) >= 3 and word[-1] in "ıiuü":
        base = word[:-2] if len(word) >= 4 and word[-2] == "s" and word[-3] in _VOWELS else word[:-1]
        candidates = {base}
        if base[-1] in _HARDEN:
            candidates.add(base[:-1] + _HARDEN[base[-1]])
        for cand in candidates:
            # Kısa kökler ("ağı" -> "ağ") yalnızca zeyrek de doğrularsa
            if len(cand) >= 3 or cand in word_lemmas:
                forms.add(cand)
    # Not: terim kelimesinin zeyrek kökleri biçim olarak EKLENMEZ. Terimler zaten yalın
    # hâlde girilir; kökleri eklemek "işlemci" -> "işlem", "dizi" -> "diz" gibi türetme
    # köklerine inip "işlemini"/"dizin" gibi yanlış eşleşmelere yol açıyordu.
    return frozenset(forms)


@dataclass(frozen=True)
class TermPattern:
    term_id: int
    words: tuple[frozenset[str], ...]  # her kelime için kabul edilen biçimler
    source: str


def build_patterns(terms) -> list[TermPattern]:
    patterns = []
    for term in terms:
        for name in term.all_names():
            words = [t.norm for t in tokenize(name)]
            if not words:
                continue
            last = len(words) - 1
            forms = tuple(_forms_for(w, compound_head=(i == last and last > 0)) for i, w in enumerate(words))
            patterns.append(TermPattern(term.pk, forms, name))
    # Uzun kalıplar önce: çakışmalarda daha özel terim kazansın
    patterns.sort(key=lambda p: (-len(p.words), -sum(len(min(f, key=len)) for f in p.words)))
    return patterns


def _suffix_ok(rest: str) -> bool:
    return rest == "" or (len(rest) <= MAX_SUFFIX_LEN and SUFFIX_RE.fullmatch(rest) is not None)


def token_matches(token: Token, forms: frozenset[str], threshold: float, fuzzy_min: int) -> bool:
    word = token.norm
    if word in forms:
        return True
    # Kelime kendisi sözlükte bir kökse ("dizin") o okumayı tercih et; "dizi+n" sayma
    if token.lemmas & forms and word not in token.lemmas:
        return True
    for form in forms:
        if len(form) >= 3 and len(word) > len(form) and word.startswith(form) and _suffix_ok(word[len(form):]):
            return True
    if len(word) < fuzzy_min:
        return False
    for form in forms:
        if len(form) < fuzzy_min:
            continue
        if fuzz.ratio(word, form) >= threshold:
            return True
        if len(word) > len(form) and fuzz.ratio(word[: len(form)], form) >= threshold and _suffix_ok(word[len(form):]):
            return True
    return False


@dataclass
class MatchResult:
    term_ids: list[int]  # ilk geçiş sırasına göre, tekrarsız
    spans: list[list[int]]  # [başlangıç, bitiş, terim_id] (orijinal metindeki karakter konumları)


def find_terms(text: str, patterns: list[TermPattern]) -> MatchResult:
    cfg = settings.TERM_MATCHING
    threshold, fuzzy_min = cfg["FUZZY_THRESHOLD"], cfg["FUZZY_MIN_LENGTH"]
    tokens = tokenize(text)
    for tok in tokens:
        tok.lemmas = lemmas(tok.norm)

    taken = [False] * len(tokens)
    found: list[tuple[int, int, int]] = []  # (ilk_token, son_token, term_id)
    for pattern in patterns:
        n = len(pattern.words)
        for i in range(len(tokens) - n + 1):
            if any(taken[i : i + n]):
                continue
            if all(token_matches(tokens[i + k], pattern.words[k], threshold, fuzzy_min) for k in range(n)):
                for k in range(i, i + n):
                    taken[k] = True
                found.append((i, i + n - 1, pattern.term_id))

    found.sort()
    term_ids: list[int] = []
    for _, _, tid in found:
        if tid not in term_ids:
            term_ids.append(tid)
    spans = [[tokens[a].start, tokens[b].end, tid] for a, b, tid in found]
    return MatchResult(term_ids, spans)


# --- alan başına önbellekli indeks ---------------------------------------------------

_index_cache: dict[int, list[TermPattern]] = {}
_index_lock = threading.Lock()


def invalidate_index():
    with _index_lock:
        _index_cache.clear()


def get_patterns(domain_id: int) -> list[TermPattern]:
    """Senkron (ORM) — async koddan database_sync_to_async ile çağırın."""
    with _index_lock:
        cached = _index_cache.get(domain_id)
    if cached is not None:
        return cached
    from .models import Term

    patterns = build_patterns(Term.objects.filter(domain_id=domain_id, is_active=True))
    with _index_lock:
        _index_cache[domain_id] = patterns
    return patterns


def match_domain_terms(text: str, domain_id: int) -> MatchResult:
    return find_terms(text, get_patterns(domain_id))
