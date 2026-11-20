from django.contrib import admin

from .models import LectureSession, TranscriptSegment


class TranscriptSegmentInline(admin.TabularInline):
    model = TranscriptSegment
    extra = 0
    fields = ("start_ms", "end_ms", "text")
    readonly_fields = ("start_ms", "end_ms")
    show_change_link = True


@admin.register(LectureSession)
class LectureSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "room_code", "domain", "speaker", "status", "created_at", "segment_count")
    list_filter = ("status", "domain")
    search_fields = ("title", "room_code")
    readonly_fields = ("room_code", "created_at", "started_at", "ended_at")
    inlines = [TranscriptSegmentInline]

    @admin.display(description="bölüm")
    def segment_count(self, obj):
        return obj.segments.count()


@admin.register(TranscriptSegment)
class TranscriptSegmentAdmin(admin.ModelAdmin):
    list_display = ("session", "start_ms", "text")
    list_filter = ("session",)
    search_fields = ("text",)
    filter_horizontal = ("detected_terms",)
