"""Keyword extraction and post-scrape normalization pipeline.

Post-scrape normalization
-------------------------
Call run_normalization_pipeline(db) after all scrapers complete.  Steps run
in this order:

  0. tag_items_without_keywords  – KeyBERT extraction for abstract-only items
  1. lowercase_keywords          – lower-case every keyword; merge exact dups
  2. merge_near_duplicates       – fuzzy-merge near-dups (thefuzz, threshold 90)
  3. expand_abbreviations        – expand known short forms to canonical terms
  4. remove_stop_keywords        – delete analytically meaningless stand-alones
  5. recalculate_weights         – recompute 0–1 weight from item-type counts
  6. print_summary               – report totals and top-30 keywords by weight
"""
from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache
from typing import TYPE_CHECKING

import sqlite_utils

if TYPE_CHECKING:
    from keybert import KeyBERT as _KBType

# ---------------------------------------------------------------------------
# Music-theory domain vocabulary used as pre-scored candidates
# ---------------------------------------------------------------------------
# Organised by domain; the flat list is what KeyBERT uses.

DOMAIN_BY_CATEGORY: dict[str, list[str]] = {
    "pitch_and_harmony": [
        "pitch class", "pitch-class set theory", "pitch space", "pitch proximity",
        "interval class", "interval vector", "prime form", "normal form", "set class",
        "trichord", "tetrachord", "hexachord", "aggregate", "chromaticism", "diatonicism",
        "modality", "tonality", "atonality", "pantonality", "extended tonality",
        "harmonic function", "harmonic rhythm", "chord grammar", "chord progression",
        "voice leading", "voice exchange", "parallel motion", "contrary motion",
        "oblique motion", "doubling", "part writing", "functional harmony",
        "non-functional harmony", "planing", "harmonic ambiguity", "harmonic prolongation",
        "harmonic substitution", "secondary dominant", "borrowed chord", "mixture",
        "enharmonic reinterpretation", "pivot chord", "modulation", "tonicization",
        "tonal center", "tonic", "dominant", "subdominant", "leading tone",
        "common-tone modulation",
    ],
    "counterpoint_and_voice_leading": [
        "counterpoint", "species counterpoint", "first species", "second species",
        "third species", "fourth species", "fifth species", "free counterpoint",
        "invertible counterpoint", "double counterpoint", "imitation", "canon", "fugue",
        "fugal exposition", "stretto", "augmentation", "diminution", "inversion",
        "retrograde", "retrograde inversion", "cantus firmus", "suspension",
        "passing tone", "neighbor tone", "appoggiatura", "escape tone", "anticipation",
        "pedal point", "voice crossing", "voice overlap",
    ],
    "serialism_and_post_tonal": [
        "twelve-tone technique", "tone row", "row class", "row form", "row matrix",
        "combinatoriality", "hexachordal combinatoriality", "invariance", "segmentation",
        "serialism", "integral serialism", "total serialism", "post-tonal theory",
        "atonal voice leading", "transpositional symmetry", "inversional symmetry",
        "Z-relation", "complement relation", "all-interval set", "all-combinatorial set",
    ],
    "form_and_structure": [
        "musical form", "sonata form", "sonata theory", "exposition", "development",
        "recapitulation", "coda", "transition", "medial caesura",
        "essential expositional closure", "binary form", "ternary form", "rondo",
        "variation form", "theme and variations", "strophic form", "through-composed",
        "sectional form", "continuous form", "rotational form", "arch form",
        "sentence", "period", "phrase", "phrase rhythm", "hypermeter",
        "formal function", "loose-knit", "tight-knit",
    ],
    "schenkerian_analysis": [
        "Schenkerian analysis", "Ursatz", "Urlinie", "Bassbrechung", "Stufe",
        "scale degree", "structural level", "foreground", "middleground", "background",
        "prolongation", "arpeggiation", "linear progression", "voice leading graph",
        "reduction", "interruption", "initial ascent", "cover tone", "inner voice",
        "obligatory register",
    ],
    "rhythm_and_meter": [
        "meter", "hypermeter", "metric hierarchy", "metric dissonance", "metric ambiguity",
        "syncopation", "hemiola", "polyrhythm", "polymeter", "isorhythm", "rhythm",
        "rhythmic grouping", "rhythmic reduction", "beat", "pulse", "tactus", "tempo",
        "rubato", "groove", "swing", "additive rhythm", "divisive rhythm", "aksak",
        "cross-rhythm", "rhythmic hierarchy",
    ],
    "neo_riemannian_and_transformational": [
        "Neo-Riemannian theory", "transformational theory", "Tonnetz",
        "parsimonious voice leading", "triadic transformation", "Leittonwechsel",
        "parallel transformation", "relative transformation", "hexatonic system",
        "octatonic system", "diatonic system", "PLR group", "contextual inversion",
        "commutative group", "generalized interval system", "network analysis",
        "arrow graph", "spatial music theory",
    ],
    "timbre_texture_orchestration": [
        "timbre", "orchestration", "instrumentation", "texture", "monophony",
        "homophony", "polyphony", "heterophony", "density", "register", "range",
        "spectral music theory", "spectralism", "acoustic ecology", "electroacoustic music",
        "sound mass", "microtonality", "extended techniques", "noise music",
    ],
    "cognition_perception_psychology": [
        "music cognition", "music perception", "music psychology", "auditory scene analysis",
        "auditory streaming", "grouping", "expectation", "surprise", "tension and release",
        "tonal hierarchy", "probe tone method", "key-finding", "melodic contour",
        "melodic accent", "musical memory", "absolute pitch", "relative pitch",
        "embodied cognition", "enactivism", "empirical musicology",
    ],
    "subfields_and_methodology": [
        "corpus analysis", "computational musicology", "music and language",
        "music and meaning", "music and gesture", "music and narrative", "topic theory",
        "hermeneutics", "phenomenology", "semiotics", "music and emotion",
        "music and embodiment", "performance analysis", "performance theory",
        "historically informed performance", "improvisation", "jazz theory", "jazz harmony",
        "blues", "popular music theory", "rock music analysis", "film music",
        "hip-hop", "public music theory", "cold war",
        "music and film", "leitmotif", "underscore", "diegetic music", "ethnomusicology",
        "world music theory", "non-Western music theory", "just intonation",
        "equal temperament", "tuning systems", "music and politics", "music and gender",
        "feminist music theory", "queer music theory", "critical race theory in music",
        "disability studies in music", "ecomusicology", "music and technology",
        "electronic music", "algorithmic composition", "generative music",
        "music information retrieval", "digital musicology", "music and mathematics",
        "music and philosophy", "analytical philosophy of music", "music ontology",
        "music and theology", "church modes", "plainchant", "medieval music theory",
        "Renaissance music theory", "Baroque music theory", "Classical music theory",
        "Romantic music theory", "twentieth-century music theory",
        "contemporary music theory", "post-colonial music theory", "global music theory",
    ],
    "historical_theorist_traditions": [
        "Rameauian theory", "basse fondamentale", "fundamental bass", "corps sonore",
        "Fuxian counterpoint", "Riemannian theory", "harmonic dualism", "Klang",
        "Schoenbergian theory", "developing variation", "musical idea", "Schenkerian theory",
        "organic unity", "Reti motivic analysis", "thematic process", "Reti transformation",
        "Meyer expectation theory", "implication-realization model", "gap-fill",
        "Lerdahl-Jackendoff theory", "generative theory of tonal music", "preference rules",
        "well-formedness rules", "metrical accent", "phenomenal accent", "structural accent",
        "Narmourian theory", "registral direction", "intervallic difference",
        "registral return", "proximity", "closure", "Lewinean theory", "interval function",
        "IFUNC", "transformation network", "Forte set theory", "Forte name",
        "similarity relations", "Kostka-Payne theory", "diatonic harmony",
        "Aldwell-Schachter theory", "Caplin formal theory", "Hepokoski-Darcy sonata theory",
        "dialogic form", "Rothstein phrase rhythm", "Cohn hexatonic theory",
        "Tymoczko voice-leading geometry", "voice-leading space", "chord geometry",
        "Huron expectation theory", "ITPRA theory", "sweet anticipation",
        "Gjerdingen schema theory", "galant schemata", "Romanesca", "Monte", "Fonte",
        "Meyer schema", "Do-Re-Mi schema", "Prinner", "Piston orchestration theory",
        "Adorno music sociology", "negative dialectics in music", "Dahlhaus historicism",
        "McClary feminist musicology", "Kerman new musicology", "Cook music and meaning",
        "Tagg popular music analysis", "Nettl ethnomusicological theory", "Agawu topic theory",
        "Hatten musical troping", "Ratner topic theory", "Tarasti musical semiotics",
        "Nattiez semiology", "Ruwet paradigmatic analysis", "London meter theory",
        "Hasty meter as rhythm", "Krebs metric dissonance theory",
        "Temperley probabilistic theory", "Tonal pitch space", "Lerdahl tonal tension",
    ],
}

# Flat list for KeyBERT candidate scoring
DOMAIN_TERMS: list[str] = [t for terms in DOMAIN_BY_CATEGORY.values() for t in terms]
_DOMAIN_LOWER = [t.lower() for t in DOMAIN_TERMS]

# Keyword → domain name (lowercase), for cloud color-coding
KEYWORD_DOMAIN: dict[str, str] = {
    t.lower(): cat
    for cat, terms in DOMAIN_BY_CATEGORY.items()
    for t in terms
}

# Domain → CSS color token
DOMAIN_COLOR: dict[str, str] = {
    "pitch_and_harmony":                "gold",
    "neo_riemannian_and_transformational": "gold",
    "rhythm_and_meter":                 "blue",
    "form_and_structure":               "green",
    "schenkerian_analysis":             "green",
    "timbre_texture_orchestration":     "red",
    "cognition_perception_psychology":  "purple",
    "subfields_and_methodology":        "purple",
    "historical_theorist_traditions":   "purple",
    "counterpoint_and_voice_leading":   "grey",
    "serialism_and_post_tonal":         "grey",
}

# Minimum cosine similarity to include a keyword from the domain pass
_THRESHOLD = 0.25

# ---------------------------------------------------------------------------
# Normalization constants
# ---------------------------------------------------------------------------

FUZZY_THRESHOLD: int = 90  # fuzz.ratio threshold for near-duplicate merging

# Short forms (already lowercased, since step 1 runs first) → canonical term.
# All canonical terms are lowercase to stay consistent with the pipeline.
ABBREVIATION_MAP: dict[str, str] = {
    # Pitch-class set theory
    "pc set":                   "pitch-class set theory",
    "pc sets":                  "pitch-class set theory",
    "set theory":               "pitch-class set theory",
    "pitch class set":          "pitch-class set theory",
    "pitch-class set":          "pitch-class set theory",
    "pitch class":              "pitch-class",
    # Neo-Riemannian
    "neo-r":                    "neo-riemannian theory",
    "neo-riemannian":           "neo-riemannian theory",
    # Schenkerian
    "schenkerian":              "schenkerian analysis",
    "schenker":                 "schenkerian analysis",
    # Transformational theory
    "transformational":         "transformational theory",
    # British/American spelling variants
    "metre":                    "meter",
    "metres":                   "meter",
    # Rhythm/metric
    "rhythmic":                 "rhythm",
    # Spectral / microtonal
    "spectral":                 "spectralism",
    "microtonal":               "microtonality",
    # Twelve-tone / serial variants → canonical domain term
    "twelve":                   "twelve-tone technique",
    "twelve tone":              "twelve-tone technique",
    "twelve note":              "twelve-tone technique",
    "twelve-note":              "twelve-tone technique",
    "twelve-note technique":    "twelve-tone technique",
    "twelve-note row":          "twelve-tone technique",
    "twelve tone technique":    "twelve-tone technique",
    # Form variants
    "formal":                   "form",
    # Analysis variants → music analysis
    "analytical":               "music analysis",
    "analytic":                 "music analysis",
    "analysing":                "music analysis",
    "analyses":                 "music analysis",
    # Hip-hop
    "hip":                      "hip-hop",
    "hip hop":                  "hip-hop",
    # Ordinal century adjectives → compound forms
    "sixteenth":                "sixteenth century",
    "seventeenth":              "seventeenth century",
    "eighteenth":               "eighteenth century",
    "nineteenth":               "nineteenth century",
    "twentieth":                "twentieth century",
    "twenty-first":             "twenty-first century",
}

# Stand-alone keywords with no analytical specificity.
# A keyword is removed only when its full text equals one of these strings
# (compound terms like "music theory" or "harmonic analysis" are kept).
STOP_KEYWORDS: frozenset[str] = frozenset([
    "music", "musical", "theory", "analysis",
    # Front/back matter artefacts from title-based extraction
    "matter", "cover", "issue", "volume", "contributors", "information",
    "cover matter", "issue cover", "issue cover matter",
    "sam", "sam volume", "sam volume issue",
    "volume issue", "volume issue cover",
    # Table-of-contents / letter / intro artefacts
    "contents", "table", "table contents", "letter", "introduction",
    "volume 16 issue", "volume 17 issue", "volume 18 issue",
    "16 issue cover", "17 issue cover", "18 issue cover",
    "sam volume 16", "sam volume 17", "sam volume 18",
    # Generic words that surface from short titles/abstracts with no specificity
    "response", "time", "century", "language", "editor", "year", "number",
    "example", "point", "way", "kind", "type", "level", "place", "use",
    "approach", "question", "idea", "term",
    # Common given names extracted as proper nouns from book-review titles
    "david", "john", "robert", "richard", "james", "william", "michael",
    "joseph", "peter", "charles", "mark", "thomas", "paul", "daniel",
    "steven", "stephen", "andrew", "christopher", "edward", "george",
    "anna", "mary", "susan", "elizabeth", "barbara", "patricia", "linda",
    "carol", "ruth", "helen", "janet",
    # Short first names (≤4 chars) not caught by the length filter
    "carl", "ian", "jim", "ben", "don", "bob", "max", "leo",
    "sal", "lou", "tom", "ray", "joe", "ron", "ken", "jay", "amy",
    "ann", "sue", "kay", "kim", "gary", "hans", "otto", "kurt",
    "hugo", "leon", "jean", "lars", "rolf", "fred", "jack", "joel",
    "ryan", "alan", "adam", "eric", "erik", "evan",
    "alex", "andy", "aaron", "roger", "frank", "harry", "larry",
    "barry", "terry", "jerry", "henry",
    # Longer first names
    "bill", "ernst", "jeff", "allen", "scott", "milton", "bela",
    "igor", "arnold", "elliott", "alban",
    # Titles / honorifics
    "mr", "ms", "dr", "prof",
    # Generic English words not caught by KeyBERT's stop-word list
    "call", "what", "life", "view", "book", "open", "world", "order",
    "guide", "mind", "basic", "reply", "brief", "class", "word",
    "text", "list", "show", "case", "area", "note", "page",
    "role", "body", "line", "hear", "real", "said", "such",
    "than", "being", "last", "aspects", "aspect", "good", "high",
    "great", "focus", "logic", "people", "essays", "essay",
    "will", "past", "large", "free", "code", "tool", "lost",
    "city", "thought", "middle", "edited", "problem", "problems",
    "lines", "meta",
    # Standalone words only meaningful in compound forms
    "cold", "live",
    # Misc noise / extraction artefacts
    "sixtes", "blue", "selected", "possible", "sulle", "tales",
    # Geographic terms too broad to be meaningful alone
    "york",
    # Compound-only terms meaningless as standalone keywords
    "cross",
    # Editorial / housekeeping artefacts
    "correction", "corrections", "erratum", "errata",
    "editorial", "conference", "papers", "reviews", "review",
    # Compound term that is too generic as a standalone keyword
    "music theory",
    # Short foreign-language articles / prepositions / particles
    # (2–3 chars handled by the extraction length guard; these 4-char ones slip through)
    "eine", "avec", "dans", "pour", "mais", "oder", "über", "nach",
    "beim", "wird", "auch", "sich", "dass", "dalla", "degli", "delle",
    "nella", "dello", "para", "como", "pero", "sino",
    # OL / library catalog classification phrases (too generic for music theory)
    "history and criticism", "criticism and interpretation",
    "music, history and criticism",
    "music, history and criticism, 19th century",
    "music, history and criticism, 20th century",
    "music, history and criticism, 18th century",
    "music, history and criticism, 17th century",
    "composers, biography", "music, social aspects",
    "music, philosophy and aesthetics", "philosophy and aesthetics",
    "analysis, appreciation", "music, british, history and criticism",
    "music, american, history and criticism",
    "music, german", "music, french", "music, italian",
    "music, russian", "music, austrian", "music, european",
    # Generic standalone terms surfaced from OL/CUP subject tags
    "biography", "musicians", "social aspects",
    "letters", "cambridge", "companion", "studies",
    "art", "practice", "context", "america", "musical criticism",
    "psychology", "computer",
    # LCSH geographic/categorical compound phrases
    "composers, great britain", "composers, germany", "music, british", "music, american",
    "musicians, biography", "psychological aspects", "political aspects", "instruction & study",
    "opera, italy", "opera, history and criticism", "songs and music", "catholic church",
    "music, psychological aspects", "music, history and criticism, 500-1400",
    # Foreign-language genre/form terms (no non-ASCII but still non-English)
    "musik", "musique", "oper",
    # Pure generics with no analytical value
    "history", "general", "books", "authors", "textbooks", "encyclopedia", "bibliography",
    "appreciation", "making", "words", "understanding", "nature", "origins",
    "sounds", "conversation", "interview", "construction", "evolution",
    "social", "relationships", "critical", "historical", "perspectives",
    "cycles", "correspondence", "writings", "british",
    # First-name fragments extracted from composer full names
    "heinrich", "leonard", "anton", "johann", "alexander", "benjamin", "arthur", "edgard", "luigi",
    # Geographic terms too broad to be useful
    "england", "london", "france", "britain",
    # LCSH compounds
    "biography & autobiography", "opera, france",
    # Generic words with no analytical value
    "communications", "report", "commentary", "special", "complete", "explorations",
    "other", "becoming", "systems", "structures", "models", "principles", "concepts",
    "patterns", "interaction", "theoretical", "multiple", "sources", "comments",
    "moment", "generalized", "common", "design", "reading", "science", "reflections",
    "techniques", "organization", "university", "topics", "materials", "combination",
    "relations", "formal", "analytical", "analytic", "analysing", "analyses",
    # LCSH analysis compounds
    "symphonies, analysis, appreciation", "string quartets, analysis, appreciation",
    "analyse musicale", "musikalische analyse", "muzikale analyse",
])

# Regex patterns matching editorial/boilerplate article titles to skip during
# title-based keyword extraction.
import re as _re
_EDITORIAL_TITLE_RE = _re.compile(
    r"^\s*(\[?letter\b|back\s+matter|front\s+matter|cover|acknowledgements?|acknowledgments?|"
    r"in\s+memoriam|editorial\s+notes?|instructions?\s+for\s+contributors?|"
    r"errata|corrigendum|corrigenda|index|preface|foreword|introduction|"
    r"volume\s+\d|vol\.\s*\d|issue\s+\d|table\s+of\s+contents|"
    r"announcements?|news\s+and\s+notes|notices?|reviews?\s+editor|"
    r"sam\s+volume|back\s+issues?)",
    _re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# KeyBERT singleton — model load is expensive, do it once
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_model() -> "_KBType":
    from keybert import KeyBERT
    return KeyBERT()


# ---------------------------------------------------------------------------
# Keyword extraction (used by scrapers and pipeline step 0)
# ---------------------------------------------------------------------------

# Sorted longest-first so substring matching prefers the most specific term
_DOMAIN_SORTED: list[str] = sorted(_DOMAIN_LOWER, key=len, reverse=True)

# Abbreviated prefix → canonical domain term, for cases where a title uses
# the shortened form (e.g. "neo-riemannian transformations" rather than
# "neo-riemannian theory").  Only prefixes that are unambiguous are listed.
_DOMAIN_PREFIX_MAP: dict[str, str] = {
    "neo-riemannian":        "neo-riemannian theory",
    "post-tonal":            "post-tonal theory",
    "pitch-class set":       "pitch-class set theory",
    "schenkerian":           "schenkerian analysis",
    "twelve-tone":           "twelve-tone technique",
    "transformational":      "transformational theory",
    "hexachordal":           "hexachordal combinatoriality",
    "forte":                 "forte set theory",
    "gjerdingen":            "gjerdingen schema theory",
    "lerdahl-jackendoff":    "lerdahl-jackendoff theory",
    "hepokoski-darcy":       "hepokoski-darcy sonata theory",
    "caplin":                "caplin formal theory",
    "tymoczko":              "tymoczko voice-leading geometry",
    "riemannian":            "riemannian theory",
    "lewinean":              "lewinean theory",
    "narmourian":            "narmourian theory",
}

# Common English words that appear capitalised in titles but are not proper nouns
_COMMON_TITLE_WORDS: frozenset[str] = frozenset({
    "the", "a", "an", "in", "on", "at", "for", "of", "to", "and", "or",
    "but", "nor", "yet", "so", "with", "by", "as", "if", "is", "are",
    "was", "were", "be", "been", "have", "has", "had", "do", "does", "did",
    "that", "this", "these", "those", "its", "his", "her", "their", "our",
    "my", "your", "we", "they", "he", "she", "it", "i", "new", "old",
    "some", "any", "all", "both", "each", "every", "no", "not",
    "part", "vol", "op", "opus", "no", "issue", "review", "essay", "notes",
    "music", "musical",
    # Generic analytical / descriptive words
    "use", "uses", "using", "study", "analysis", "approach", "approaches",
    "theory", "theories", "toward", "towards", "beyond", "between", "among",
    "from", "into", "through", "about", "after", "before", "since", "until",
    "role", "case", "cases", "form", "forms", "style", "styles", "concept",
    "function", "structure", "process", "model", "method", "technique",
    "tradition", "history", "critique", "reception", "voice", "sound",
    "work", "works", "song", "songs", "piece", "pieces",
    "one", "two", "three", "four", "five", "six", "seven", "eight",
    "first", "second", "third", "late", "early", "recent", "modern",
    # Geographical / political adjectives
    "western", "eastern", "northern", "southern", "central",
    "american", "european", "german", "french", "english", "italian",
    "russian", "japanese", "chinese", "african", "latin", "democratic",
    "republic", "national", "international", "global",
    # Common article-title verbs / prepositions easily confused with names
    "post", "neo", "pre", "anti", "non",
})

_POSSESSIVE_RE = re.compile(r"'s$")
_PROPER_RE = re.compile(r"\b([A-ZÀÂÄÉÈÊËÎÏÔÙÛÜ][a-zàâäéèêëîïôùûü]{1,}(?:'s)?)\b")


def _domain_substring_match(title_lower: str) -> list[str]:
    """
    Return all domain terms that appear verbatim (as substrings) in the title.
    Longer terms are matched first; once a span is claimed it is not re-matched.
    Falls back to _DOMAIN_PREFIX_MAP for abbreviated/hyphenated forms.
    """
    found: list[str] = []
    remaining = title_lower

    for term in _DOMAIN_SORTED:
        if term in remaining:
            found.append(term)
            remaining = remaining.replace(term, " " * len(term), 1)

    # Prefix fallback: catch "neo-riemannian transformations" → "neo-riemannian theory"
    for prefix, canonical in _DOMAIN_PREFIX_MAP.items():
        if canonical not in found and prefix in remaining:
            found.append(canonical)
            remaining = remaining.replace(prefix, " " * len(prefix), 1)

    return found


def _extract_proper_nouns(raw_title: str, exclude: set[str]) -> list[str]:
    """
    Extract capitalised words from a title that are likely proper nouns
    (composer/theorist names, work titles) and are not already covered by
    a domain match.
    """
    results: list[str] = []
    seen: set[str] = set()
    for m in _PROPER_RE.findall(raw_title):
        low = _POSSESSIVE_RE.sub("", m.lower())   # strip possessive suffix properly
        if len(low) < 4:  # 3-char names (Ian, Jim, Don…) are almost never meaningful alone
            continue
        if low in _COMMON_TITLE_WORDS or low in seen:
            continue
        if any(low in ex or ex in low for ex in exclude):
            continue
        seen.add(low)
        results.append(low)
    return results


def _remove_redundant_ngrams(kws: list[str], domain_set: set[str]) -> list[str]:
    """
    Drop multi-word phrases whose component words all appear as individual
    extracted unigrams AND that are not established domain compound terms.
    e.g. ["berg", "wozzeck", "berg wozzeck"] → ["berg", "wozzeck"]
         ["voice leading"] kept even if "voice" is a unigram (it's a domain term)
    """
    unigrams = {kw for kw in kws if len(kw.split()) == 1}
    result = []
    for kw in kws:
        words = kw.split()
        if len(words) == 1 or kw in domain_set:
            result.append(kw)
        elif not all(w in unigrams for w in words):
            result.append(kw)
        # else: all words individually present and not a domain compound → drop
    return result


def extract_keywords_from_title(raw_title: str, top_n: int = 3) -> list[str]:
    """
    Extract up to *top_n* keywords from a short title string.

    Strategy:
    1. Direct substring match against the full domain vocabulary (longest
       terms first) — reliably captures compound terms like "voice leading".
    2. Proper-noun extraction for capitalised words not covered by step 1
       (composer/theorist names, work titles, etc.).

    No semantic embedding is used for titles — they are too short for reliable
    cosine similarity scoring.
    """
    if not raw_title:
        return []
    title_lower = raw_title.lower()

    domain_kws = _domain_substring_match(title_lower)
    proper_nouns = _extract_proper_nouns(raw_title, exclude=set(domain_kws))

    merged = list(dict.fromkeys(domain_kws + proper_nouns))
    return merged[:top_n]


def extract_keywords(text: str, top_n: int = 8) -> list[str]:
    """
    Return up to *top_n* keywords for an abstract using a two-pass KeyBERT strategy.

    Pass 1 — domain scoring
        Score every term in DOMAIN_TERMS against the document. Terms above
        _THRESHOLD are included verbatim.

    Pass 2 — free extraction (bigrams only, higher diversity)
        Extract novel 1–2-word phrases not already covered by pass 1.
        Overlapping n-grams (where all component words are already individually
        extracted) are pruned.

    Returns a deduplicated, relevance-sorted list of lowercase keyword strings.
    """
    text = _clean(text)
    if not text:
        return []

    model = _get_model()

    domain_hits: list[tuple[str, float]] = model.extract_keywords(
        text, candidates=_DOMAIN_LOWER, top_n=len(_DOMAIN_LOWER),
    )
    domain_kws = {kw for kw, score in domain_hits if score >= _THRESHOLD}

    free_hits: list[tuple[str, float]] = model.extract_keywords(
        text,
        keyphrase_ngram_range=(1, 2),
        stop_words="english",
        use_mmr=True,
        diversity=0.7,
        top_n=top_n,
        nr_candidates=max(top_n * 3, 20),
    )
    # Reject single tokens shorter than 4 chars that aren't established
    # short-form music terms (genre tags, solfège, etc.).
    _SHORT_OK = frozenset({"set", "rap", "key", "pop", "edm", "ars", "art", "air"})
    free_kws = [
        kw for kw, score in free_hits
        if score >= _THRESHOLD + 0.05
        and not _covered_by_domain(kw, domain_kws)
        and (len(kw) >= 4 or kw in _SHORT_OK)
    ]

    merged_raw = list(domain_kws) + free_kws
    merged = list(dict.fromkeys(kw.strip().lower() for kw in merged_raw if kw.strip()))
    merged = _remove_redundant_ngrams(merged, domain_kws)
    return merged[:top_n]


def tag_items_without_keywords(db: sqlite_utils.Database) -> int:
    """
    For every item that has no *explicit* keywords:
    - If it has an abstract, run KeyBERT on the abstract (weight 0.8).
    - Else if it has a title, run KeyBERT on the title (weight 0.5).

    Returns the number of items processed.
    """
    from db import add_keywords_to_item  # avoid circular import at module level

    # Abstract-based extraction (higher confidence)
    abstract_query = """
        SELECT i.id, i.abstract
        FROM items i
        WHERE i.abstract IS NOT NULL
          AND i.abstract != ''
          AND NOT EXISTS (
              SELECT 1 FROM item_keywords ik
              WHERE ik.item_id = i.id AND ik.source = 'explicit'
          )
    """
    abstract_rows = list(db.execute(abstract_query).fetchall())
    processed = 0

    for item_id, abstract in abstract_rows:
        keywords = extract_keywords(abstract)
        if keywords:
            add_keywords_to_item(db, item_id, keywords, source="extracted", weight=0.8)
        processed += 1

    # Title-based extraction for items with no abstract and no keywords yet
    title_query = """
        SELECT i.id, i.title
        FROM items i
        WHERE (i.abstract IS NULL OR i.abstract = '')
          AND i.title IS NOT NULL
          AND i.title != ''
          AND NOT EXISTS (
              SELECT 1 FROM item_keywords ik
              WHERE ik.item_id = i.id
          )
    """
    title_rows = list(db.execute(title_query).fetchall())

    for item_id, title in title_rows:
        if _EDITORIAL_TITLE_RE.match(title):
            continue
        keywords = extract_keywords_from_title(title, top_n=3)
        if keywords:
            add_keywords_to_item(db, item_id, keywords, source="extracted", weight=0.5)
        processed += 1

    return processed


# ---------------------------------------------------------------------------
# Low-level merge helper
# ---------------------------------------------------------------------------

def _merge_keyword(
    db: sqlite_utils.Database, keep_id: int, drop_id: int
) -> None:
    """Re-point all item_keywords from *drop_id* to *keep_id*, then delete *drop_id*."""
    # UPDATE OR IGNORE skips rows where the (item_id, keep_id) pair already exists.
    db.execute(
        "UPDATE OR IGNORE item_keywords SET keyword_id = ? WHERE keyword_id = ?",
        [keep_id, drop_id],
    )
    # Delete any rows that couldn't be re-pointed (pre-existing duplicates).
    db.execute("DELETE FROM item_keywords WHERE keyword_id = ?", [drop_id])
    db.execute("DELETE FROM keywords WHERE id = ?", [drop_id])


# ---------------------------------------------------------------------------
# Pipeline step 1: lowercase
# ---------------------------------------------------------------------------

def lowercase_keywords(db: sqlite_utils.Database) -> int:
    """
    Lowercase every keyword in the keywords table in place.  Where lowercasing
    produces a duplicate (e.g. "Harmony" and "harmony" both exist), merge the
    lower-link-count row into the higher-link-count row.

    Returns the number of rows that were merged away.
    """
    rows = list(
        db.execute(
            """
            SELECT k.id, k.keyword, COUNT(ik.item_id) AS cnt
            FROM keywords k
            LEFT JOIN item_keywords ik ON ik.keyword_id = k.id
            GROUP BY k.id
            """
        ).fetchall()
    )

    # Group by lowercase form
    groups: dict[str, list[tuple[int, int]]] = defaultdict(list)  # lower → [(cnt, id)]
    for kid, kw, cnt in rows:
        groups[kw.lower()].append((cnt, kid))

    merged = 0
    with db.conn:
        for lower_form, members in groups.items():
            if len(members) == 1:
                _, kid = members[0]
                db.conn.execute(
                    "UPDATE keywords SET keyword = ? WHERE id = ? AND keyword != ?",
                    [lower_form, kid, lower_form],
                )
            else:
                members.sort(reverse=True)  # sort by cnt desc
                _, keep_id = members[0]
                for _, drop_id in members[1:]:
                    # _merge_keyword uses db.execute; call raw conn inside the same txn
                    db.conn.execute(
                        "UPDATE OR IGNORE item_keywords SET keyword_id = ? WHERE keyword_id = ?",
                        [keep_id, drop_id],
                    )
                    db.conn.execute("DELETE FROM item_keywords WHERE keyword_id = ?", [drop_id])
                    db.conn.execute("DELETE FROM keywords WHERE id = ?", [drop_id])
                    merged += 1
                db.conn.execute(
                    "UPDATE keywords SET keyword = ? WHERE id = ?",
                    [lower_form, keep_id],
                )

    return merged


# ---------------------------------------------------------------------------
# Pipeline step 2: fuzzy near-duplicate merge
# ---------------------------------------------------------------------------

def merge_near_duplicates(
    db: sqlite_utils.Database,
    threshold: int = FUZZY_THRESHOLD,
) -> int:
    """
    Compare every pair of keywords and merge pairs whose fuzz.ratio ≥ *threshold*.
    The keyword with more item_keywords links is kept as canonical; the other is
    merged into it.

    Returns the number of keywords merged away.
    """
    from thefuzz import fuzz

    rows = list(
        db.execute(
            """
            SELECT k.id, k.keyword, COUNT(ik.item_id) AS cnt
            FROM keywords k
            LEFT JOIN item_keywords ik ON ik.keyword_id = k.id
            GROUP BY k.id
            ORDER BY cnt DESC
            """
        ).fetchall()
    )

    # Build mutable lookup; iterate in count-descending order so the keyword
    # with more links is always the canonical one.
    active: dict[int, str] = {kid: kw for kid, kw, _ in rows}
    order: list[int] = [kid for kid, _, _ in rows]
    dropped: set[int] = set()
    merges: list[tuple[int, int]] = []  # (keep_id, drop_id) collected then committed in one txn

    for i, kid1 in enumerate(order):
        if kid1 in dropped:
            continue
        kw1 = active[kid1]

        for kid2 in order[i + 1 :]:
            if kid2 in dropped:
                continue
            kw2 = active[kid2]

            lo, hi = sorted([len(kw1), len(kw2)])
            if hi == 0 or lo / hi < (threshold / 100) * 0.6:
                continue

            if fuzz.ratio(kw1, kw2) >= threshold:
                merges.append((kid1, kid2))
                dropped.add(kid2)
                del active[kid2]

    with db.conn:
        for keep_id, drop_id in merges:
            db.conn.execute(
                "UPDATE OR IGNORE item_keywords SET keyword_id = ? WHERE keyword_id = ?",
                [keep_id, drop_id],
            )
            db.conn.execute("DELETE FROM item_keywords WHERE keyword_id = ?", [drop_id])
            db.conn.execute("DELETE FROM keywords WHERE id = ?", [drop_id])

    return len(merges)


# ---------------------------------------------------------------------------
# Pipeline step 3: abbreviation expansion
# ---------------------------------------------------------------------------

def expand_abbreviations(db: sqlite_utils.Database) -> int:
    """
    Replace known abbreviated keyword forms with their canonical expansions.
    If the canonical form already exists as a keyword, the short form is merged
    into it; otherwise the short form is renamed in place.

    Returns the number of keywords expanded.
    """
    def _row(sql: str, val: str) -> int | None:
        rows = db.execute(sql, [val]).fetchall()
        return rows[0][0] if rows else None

    expanded = 0
    with db.conn:
        for short, canonical in ABBREVIATION_MAP.items():
            short_id = _row("SELECT id FROM keywords WHERE keyword = ?", short)
            if short_id is None:
                continue

            canon_id = _row("SELECT id FROM keywords WHERE keyword = ?", canonical)
            if canon_id is not None and canon_id != short_id:
                db.conn.execute(
                    "UPDATE OR IGNORE item_keywords SET keyword_id = ? WHERE keyword_id = ?",
                    [canon_id, short_id],
                )
                db.conn.execute("DELETE FROM item_keywords WHERE keyword_id = ?", [short_id])
                db.conn.execute("DELETE FROM keywords WHERE id = ?", [short_id])
            elif canon_id is None:
                db.conn.execute(
                    "UPDATE keywords SET keyword = ? WHERE id = ?",
                    [canonical, short_id],
                )

            expanded += 1

    return expanded


# ---------------------------------------------------------------------------
# Pipeline step 4: stop-keyword removal
# ---------------------------------------------------------------------------

def remove_stop_keywords(db: sqlite_utils.Database) -> int:
    """
    Delete keywords whose full text exactly matches a term in STOP_KEYWORDS.
    Compound terms that merely *contain* a stop word (e.g. "music theory") are
    unaffected.

    Returns the number of keywords removed.
    """
    removed = 0
    with db.conn:
        for term in STOP_KEYWORDS:
            rows = db.conn.execute(
                "SELECT id FROM keywords WHERE keyword = ?", [term]
            ).fetchall()
            if rows:
                kid = rows[0][0]
                db.conn.execute("DELETE FROM item_keywords WHERE keyword_id = ?", [kid])
                db.conn.execute("DELETE FROM keywords WHERE id = ?", [kid])
                removed += 1
    return removed


# ---------------------------------------------------------------------------
# Pipeline step 5: weight recalculation
# ---------------------------------------------------------------------------

def recalculate_weights(db: sqlite_utils.Database) -> None:
    """
    Recompute each keyword's weight as a normalized 0–1 score:

        raw = (article_count × 1.0) + (book_count × 1.5) + (chapter_count × 0.5)
        weight = raw / max(raw across all keywords)

    Updates keywords.weight in place.
    """
    rows = list(
        db.execute(
            """
            SELECT
                k.id,
                SUM(CASE WHEN i.item_type = 'article' THEN 1.0 ELSE 0 END)  AS a,
                SUM(CASE WHEN i.item_type = 'book'    THEN 1.5 ELSE 0 END)  AS b,
                SUM(CASE WHEN i.item_type = 'chapter' THEN 0.5 ELSE 0 END)  AS c
            FROM keywords k
            LEFT JOIN item_keywords ik ON ik.keyword_id = k.id
            LEFT JOIN items i          ON i.id = ik.item_id
            GROUP BY k.id
            """
        ).fetchall()
    )

    scores: list[tuple[int, float]] = []
    for kid, a, b, c in rows:
        raw = (a or 0.0) + (b or 0.0) + (c or 0.0)
        scores.append((kid, raw))

    max_score = max((s for _, s in scores), default=1.0) or 1.0

    with db.conn:
        for kid, raw in scores:
            db.conn.execute(
                "UPDATE keywords SET weight = ? WHERE id = ?",
                [raw / max_score, kid],
            )

    # Prune keywords that have no remaining links (orphaned by merges/deletions)
    db.conn.execute(
        "DELETE FROM keywords WHERE id NOT IN (SELECT DISTINCT keyword_id FROM item_keywords)"
    )
    db.conn.commit()


# ---------------------------------------------------------------------------
# Pipeline step 6: summary report
# ---------------------------------------------------------------------------

def print_summary(db: sqlite_utils.Database) -> None:
    """Print total item / keyword counts and the top 30 keywords by weight."""
    total_items    = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    total_keywords = db.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]
    total_links    = db.execute("SELECT COUNT(*) FROM item_keywords").fetchone()[0]

    by_type = dict(
        db.execute(
            "SELECT item_type, COUNT(*) FROM items GROUP BY item_type"
        ).fetchall()
    )

    top30 = db.execute(
        """
        SELECT k.keyword, k.weight, COUNT(ik.item_id) AS links
        FROM keywords k
        LEFT JOIN item_keywords ik ON ik.keyword_id = k.id
        GROUP BY k.id
        ORDER BY k.weight DESC
        LIMIT 30
        """
    ).fetchall()

    bar = "=" * 62
    print(f"\n{bar}")
    print("  Music Theory DB — Normalization Summary")
    print(bar)
    print(f"  {'Total items:':<22} {total_items:>6,}")
    for itype in ("article", "book", "chapter"):
        n = by_type.get(itype, 0)
        if n:
            print(f"    {'  ' + itype + ':':<20} {n:>6,}")
    print(f"  {'Total keywords:':<22} {total_keywords:>6,}")
    print(f"  {'Total keyword links:':<22} {total_links:>6,}")
    print(f"\n  {'Top 30 keywords by weight':}")
    print(f"  {'keyword':<38} {'weight':>7}  {'links':>5}")
    print(f"  {'-'*38} {'-'*7}  {'-'*5}")
    for kw, weight, links in top30:
        print(f"  {kw:<38} {weight:>7.4f}  {links:>5}")
    print()


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

def run_normalization_pipeline(db: sqlite_utils.Database | None = None) -> None:
    """
    Run the full post-scrape normalization pipeline.

    Steps
    -----
    0. KeyBERT extraction for items with abstracts but no explicit keywords
    1. Lowercase all keywords; merge exact duplicates produced by casing
    2. Fuzzy-merge near-duplicates (threshold 90)
    3. Expand known abbreviations to canonical long forms
    4. Remove analytically meaningless stand-alone stop keywords
    5. Recalculate keyword weights from item-type-weighted article counts
    6. Print summary report
    """
    if db is None:
        from db import get_db
        db = get_db()

    # Step 0 — KeyBERT extraction
    print("Step 0: Extracting keywords from abstracts (KeyBERT)…", flush=True)
    n = tag_items_without_keywords(db)
    print(f"        {n} items processed.", flush=True)

    # Step 1 — Lowercase
    print("Step 1: Lowercasing keywords…", flush=True)
    n = lowercase_keywords(db)
    print(f"        {n} duplicate(s) merged by casing.", flush=True)

    # Step 2 — Fuzzy merge
    print(f"Step 2: Fuzzy-merging near-duplicates (threshold={FUZZY_THRESHOLD})…", flush=True)
    n = merge_near_duplicates(db)
    print(f"        {n} near-duplicate(s) merged.", flush=True)

    # Step 3 — Abbreviation expansion
    print("Step 3: Expanding abbreviations…", flush=True)
    n = expand_abbreviations(db)
    print(f"        {n} abbreviation(s) expanded.", flush=True)

    # Step 4 — Stop-keyword removal
    print("Step 4: Removing stop keywords…", flush=True)
    n = remove_stop_keywords(db)
    print(f"        {n} stop keyword(s) removed.", flush=True)

    # Step 5 — Weight recalculation
    print("Step 5: Recalculating keyword weights…", flush=True)
    recalculate_weights(db)
    print("        Done.", flush=True)

    # Step 6 — Summary
    print_summary(db)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def normalize_record(record: dict) -> dict:
    """Light normalisation pass before DB insert (stub — extend as needed)."""
    return record


def upsert_records(
    db: sqlite_utils.Database, table: str, records: list[dict], pk: str = "id"
) -> None:
    db[table].upsert_all(records, pk=pk)


def _clean(text: str) -> str:
    """Strip citation markers, normalize hyphens in compound terms, collapse whitespace."""
    text = re.sub(r"\(\d{4}\)", "", text)           # (2003)
    text = re.sub(r"\[\d+\]", "", text)             # [1]
    # Normalize hyphenated music terms so they match space-separated domain vocabulary
    text = re.sub(r"(?<=[a-zA-Z])-(?=[a-zA-Z])", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _covered_by_domain(phrase: str, domain_kws: set[str]) -> bool:
    """Return True if *phrase* is a substring of any domain keyword already selected."""
    p = phrase.lower()
    return any(p in dk or dk in p for dk in domain_kws)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    from db import get_db
    run_normalization_pipeline(get_db())
