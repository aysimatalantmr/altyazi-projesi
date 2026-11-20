from django import forms

from glossary.models import Domain

from .models import LectureSession, normalize_room_code


class JoinForm(forms.Form):
    room_code = forms.CharField(
        label="Oda kodu",
        max_length=12,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "characters",
                "spellcheck": "false",
                "placeholder": "ör. K7M2QX",
                "class": "input-code",
            }
        ),
    )

    def clean_room_code(self):
        code = normalize_room_code(self.cleaned_data["room_code"])
        if not LectureSession.objects.filter(room_code=code).exists():
            raise forms.ValidationError("Bu koda sahip bir oturum bulunamadı. Kodu kontrol edin.")
        return code


class SessionCreateForm(forms.ModelForm):
    domain = forms.ModelChoiceField(queryset=Domain.objects.all(), label="Alan", empty_label=None)

    class Meta:
        model = LectureSession
        fields = ["title", "domain"]
        labels = {"title": "Ders başlığı"}
        widgets = {"title": forms.TextInput(attrs={"placeholder": "ör. Veri Yapıları — 5. Hafta"})}
