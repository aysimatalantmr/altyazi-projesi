from django.core.exceptions import ValidationError
from django.db import models


class Domain(models.Model):
    name = models.CharField("alan adı", max_length=120, unique=True)
    slug = models.SlugField("kısa ad", max_length=120, unique=True)
    description = models.TextField("açıklama", blank=True)

    class Meta:
        verbose_name = "alan"
        verbose_name_plural = "alanlar"
        ordering = ["name"]

    def __str__(self):
        return self.name


def validate_aliases(value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValidationError('Takma adlar metin listesi olmalı, ör. ["stack", "yığıt"].')


class Term(models.Model):
    domain = models.ForeignKey(Domain, on_delete=models.CASCADE, related_name="terms", verbose_name="alan")
    term = models.CharField("terim", max_length=200)
    aliases = models.JSONField(
        "takma adlar",
        default=list,
        blank=True,
        validators=[validate_aliases],
        help_text='Eş anlamlılar / İngilizce karşılıklar, JSON liste: ["stack", "yığıt"]',
    )
    simple_definition = models.TextField("sade tanım", help_text="Kısa ve anlaşılır bir dille yazın.")
    image = models.ImageField("görsel", upload_to="terms/", blank=True)
    sign_video_url = models.URLField(
        "TİD video bağlantısı", blank=True, help_text="YouTube bağlantısı veya doğrudan .mp4/.webm adresi"
    )
    is_active = models.BooleanField("etkin", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "terim"
        verbose_name_plural = "terimler"
        ordering = ["domain", "term"]
        constraints = [models.UniqueConstraint(fields=["domain", "term"], name="benzersiz_alan_terim")]

    def __str__(self):
        return self.term

    def all_names(self) -> list[str]:
        names = [self.term, *(self.aliases or [])]
        seen, result = set(), []
        for name in names:
            name = (name or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                result.append(name)
        return result

    def sign_video_embed(self) -> dict | None:
        """Videoyu şablonda nasıl göstereceğimizi belirler."""
        from .video import video_embed

        return video_embed(self.sign_video_url)

    def to_card(self) -> dict:
        return {
            "id": self.pk,
            "term": self.term,
            "definition": self.simple_definition,
            "image": self.image.url if self.image else None,
            "video": self.sign_video_embed(),
        }
