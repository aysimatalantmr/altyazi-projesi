from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import JoinForm, SessionCreateForm
from .models import LectureSession, normalize_room_code


def _get_session(room_code: str) -> LectureSession:
    return get_object_or_404(LectureSession.objects.select_related("domain"), room_code=normalize_room_code(room_code))


def home(request):
    form = JoinForm(request.GET or None) if "room_code" in request.GET else JoinForm()
    if form.is_bound and form.is_valid():
        return redirect("lectures:student_room", room_code=form.cleaned_data["room_code"])
    return render(request, "lectures/home.html", {"form": form})


def student_room(request, room_code):
    session = _get_session(room_code)
    if session.room_code != room_code:
        return redirect("lectures:student_room", room_code=session.room_code)
    return render(request, "lectures/student.html", {"session": session})


@login_required
def speaker_dashboard(request):
    form = SessionCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        session = form.save(commit=False)
        session.speaker = request.user
        session.save()
        return redirect("lectures:speaker_room", room_code=session.room_code)
    sessions = LectureSession.objects.filter(speaker=request.user).select_related("domain")[:50]
    return render(request, "lectures/speaker_dashboard.html", {"form": form, "sessions": sessions})


@login_required
def speaker_room(request, room_code):
    session = _get_session(room_code)
    if session.speaker_id != request.user.id and not request.user.is_superuser:
        raise Http404
    student_url = request.build_absolute_uri(session.get_absolute_url())
    return render(
        request,
        "lectures/speaker.html",
        {"session": session, "student_url": student_url, "partials": settings.ASR["PARTIALS"]},
    )


def _fmt_ms(ms: int) -> str:
    seconds = ms // 1000
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def build_transcript_text(session: LectureSession) -> str:
    segments = session.segments.prefetch_related("detected_terms").order_by("start_ms", "id")
    lines = [
        f"Ders: {session.title}",
        f"Alan: {session.domain.name}",
        f"Oda kodu: {session.room_code}",
    ]
    if session.started_at:
        lines.append(f"Tarih: {timezone.localtime(session.started_at):%d.%m.%Y %H:%M}")
    lines += ["", "TRANSKRİPT", "=" * 40]
    terms = {}
    for seg in segments:
        lines.append(f"[{_fmt_ms(seg.start_ms)}] {seg.text}")
        for term in seg.detected_terms.all():
            terms.setdefault(term.pk, term)
    if terms:
        lines += ["", "GEÇEN TERİMLER", "=" * 40]
        for term in sorted(terms.values(), key=lambda t: t.term.lower()):
            lines.append(f"- {term.term}: {term.simple_definition}")
    lines += ["", "Bu transkript otomatik konuşma tanıma ile oluşturulmuştur; hatalar içerebilir."]
    return "\r\n".join(lines) + "\r\n"


def transcript_txt(request, room_code):
    session = _get_session(room_code)
    # BOM: Windows Not Defteri'nde Türkçe karakterlerin doğru görünmesi için
    response = HttpResponse("﻿" + build_transcript_text(session), content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="transkript_{session.room_code}.txt"'
    return response
