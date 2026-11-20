from django.contrib import admin
from django.utils.html import format_html

from .models import Domain, Term


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "term_count")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="terim sayısı")
    def term_count(self, obj):
        return obj.terms.count()


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ("term", "domain", "alias_list", "has_image", "has_video", "is_active")
    list_filter = ("domain", "is_active")
    list_editable = ("is_active",)
    search_fields = ("term", "aliases", "simple_definition")
    readonly_fields = ("image_preview",)
    fieldsets = (
        (None, {"fields": ("domain", "term", "aliases", "simple_definition", "is_active")}),
        ("Görsel ve işaret dili", {"fields": ("image", "image_preview", "sign_video_url")}),
    )

    @admin.display(description="takma adlar")
    def alias_list(self, obj):
        return ", ".join(obj.aliases or [])

    @admin.display(description="görsel", boolean=True)
    def has_image(self, obj):
        return bool(obj.image)

    @admin.display(description="TİD", boolean=True)
    def has_video(self, obj):
        return bool(obj.sign_video_url)

    @admin.display(description="önizleme")
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height:160px;border-radius:6px">', obj.image.url)
        return "—"
