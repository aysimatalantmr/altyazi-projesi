"""Oturum verisiyle ilgili senkron (ORM) yardımcılar. Async koddan
`database_sync_to_async` ile çağrılır."""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max

from glossary.matcher import match_domain_terms
from glossary.models import Term

from .models import LectureSession, TranscriptSegment, normalize_room_code


@dataclass
class SessionContext:
    id: int
    room_code: str
    group_name: str
    speaker_id: int
    domain_id: int
    domain_name: str
    term_names: list[str]
    status: str


def get_session_context(room_code: str) -> SessionContext | None:
    session = (
        LectureSession.objects.select_related("domain").filter(room_code=normalize_room_code(room_code)).first()
    )
    if session is None:
        return None
    term_names = list(
        Term.objects.filter(domain_id=session.domain_id, is_active=True).order_by("term").values_list("term", flat=True)
    )
    return SessionContext(
        id=session.pk,
        room_code=session.room_code,
        group_name=session.group_name,
        speaker_id=session.speaker_id,
        domain_id=session.domain_id,
        domain_name=session.domain.name,
        term_names=term_names,
        status=session.status,
    )


def next_time_offset(session_id: int) -> int:
    """Oturum durdurulup yeniden başlatıldığında zaman damgaları kaldığı yerden sürsün."""
    last = TranscriptSegment.objects.filter(session_id=session_id).aggregate(m=Max("end_ms"))["m"]
    return (last + 1000) if last else 0


def set_status(session_id: int, live: bool) -> str:
    session = LectureSession.objects.get(pk=session_id)
    if live:
        session.mark_live()
    else:
        session.mark_ended()
    return session.status


@transaction.atomic
def save_final_segment(session_id: int, domain_id: int, text: str, start_ms: int, end_ms: int) -> dict:
    """Kesin metni kaydeder, terimleri eşler; yayınlanacak olayı döndürür."""
    match = match_domain_terms(text, domain_id)
    segment = TranscriptSegment.objects.create(
        session_id=session_id, text=text, start_ms=start_ms, end_ms=end_ms, term_spans=match.spans
    )
    terms = []
    if match.term_ids:
        by_id = Term.objects.in_bulk(match.term_ids)
        segment.detected_terms.set(match.term_ids)
        terms = [by_id[tid].to_card() for tid in match.term_ids if tid in by_id]
    return {"type": "final", "segment": segment.to_event(), "terms": terms}


def session_history(session_id: int) -> dict:
    session = LectureSession.objects.get(pk=session_id)
    segments = list(session.segments.order_by("start_ms", "id"))
    term_order: list[int] = []
    through = TranscriptSegment.detected_terms.through.objects.filter(transcriptsegment__session_id=session_id)
    seg_order = {s.pk: i for i, s in enumerate(segments)}
    for row in sorted(through.values("transcriptsegment_id", "term_id"), key=lambda r: seg_order.get(r["transcriptsegment_id"], 0)):
        if row["term_id"] not in term_order:
            term_order.append(row["term_id"])
    by_id = Term.objects.in_bulk(term_order)
    return {
        "type": "history",
        "status": session.status,
        "segments": [s.to_event() for s in segments],
        "terms": [by_id[t].to_card() for t in term_order if t in by_id],
    }
