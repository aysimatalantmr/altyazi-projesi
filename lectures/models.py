import secrets

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from glossary.models import Domain, Term

# Karışabilecek karakterler (0/O, 1/I/L) çıkarıldı.
ROOM_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
ROOM_CODE_LENGTH = 6


def generate_room_code() -> str:
    for _ in range(50):
        code = "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))
        if not LectureSession.objects.filter(room_code=code).exists():
            return code
    raise RuntimeError("Benzersiz oda kodu üretilemedi")


def normalize_room_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


class LectureSession(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Bekliyor"
        LIVE = "live", "Canlı"
        ENDED = "ended", "Bitti"

    title = models.CharField("başlık", max_length=200)
    domain = models.ForeignKey(Domain, on_delete=models.PROTECT, related_name="sessions", verbose_name="alan")
    speaker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lecture_sessions", verbose_name="konuşmacı"
    )
    room_code = models.CharField("oda kodu", max_length=12, unique=True, editable=False)
    status = models.CharField("durum", max_length=10, choices=Status.choices, default=Status.WAITING)
    created_at = models.DateTimeField("oluşturulma", auto_now_add=True)
    started_at = models.DateTimeField("başlangıç", null=True, blank=True)
    ended_at = models.DateTimeField("bitiş", null=True, blank=True)

    class Meta:
        verbose_name = "ders oturumu"
        verbose_name_plural = "ders oturumları"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.room_code})"

    def save(self, *args, **kwargs):
        if not self.room_code:
            self.room_code = generate_room_code()
        super().save(*args, **kwargs)

    @property
    def group_name(self) -> str:
        return f"oturum_{self.room_code}"

    def get_absolute_url(self):
        return reverse("lectures:student_room", args=[self.room_code])

    def mark_live(self):
        self.status = self.Status.LIVE
        if not self.started_at:
            self.started_at = timezone.now()
        self.ended_at = None
        self.save(update_fields=["status", "started_at", "ended_at"])

    def mark_ended(self):
        self.status = self.Status.ENDED
        self.ended_at = timezone.now()
        self.save(update_fields=["status", "ended_at"])


class TranscriptSegment(models.Model):
    session = models.ForeignKey(
        LectureSession, on_delete=models.CASCADE, related_name="segments", verbose_name="oturum"
    )
    text = models.TextField("metin")
    start_ms = models.PositiveIntegerField("başlangıç (ms)", default=0)
    end_ms = models.PositiveIntegerField("bitiş (ms)", default=0)
    detected_terms = models.ManyToManyField(Term, blank=True, related_name="segments", verbose_name="tespit edilen terimler")
    term_spans = models.JSONField(
        "terim konumları", default=list, blank=True, help_text="[[başlangıç, bitiş, terim_id], ...] karakter konumları"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "transkript bölümü"
        verbose_name_plural = "transkript bölümleri"
        ordering = ["session", "start_ms", "id"]

    def __str__(self):
        return self.text[:60]

    def to_event(self) -> dict:
        return {
            "id": self.pk,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "spans": self.term_spans,
        }
