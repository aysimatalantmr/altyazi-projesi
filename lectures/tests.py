from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from glossary.models import Domain

from . import services
from .models import ROOM_CODE_ALPHABET, LectureSession, TranscriptSegment
from .routing import websocket_urlpatterns


def make_session(username="hoca"):
    user = get_user_model().objects.create_user(username, password="parola-123")
    domain = Domain.objects.get(slug="bilgisayar-muhendisligi")
    return LectureSession.objects.create(title="Veri Yapıları", domain=domain, speaker=user), user


class LectureViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("loaddata", "bilgisayar_muhendisligi", verbosity=0)

    def test_room_code_format(self):
        session, _ = make_session()
        self.assertEqual(len(session.room_code), 6)
        self.assertTrue(set(session.room_code) <= set(ROOM_CODE_ALPHABET))

    def test_join_with_lowercase_code(self):
        session, _ = make_session()
        resp = self.client.get(reverse("lectures:home"), {"room_code": f" {session.room_code.lower()} "})
        self.assertRedirects(resp, reverse("lectures:student_room", args=[session.room_code]))

    def test_join_unknown_code(self):
        resp = self.client.get(reverse("lectures:home"), {"room_code": "ZZZZZZ"})
        self.assertContains(resp, "bulunamadı")

    def test_student_page_public(self):
        session, _ = make_session()
        resp = self.client.get(reverse("lectures:student_room", args=[session.room_code]))
        self.assertContains(resp, "Canlı altyazı")
        self.assertContains(resp, session.room_code)

    def test_speaker_pages_require_owner(self):
        session, owner = make_session()
        url = reverse("lectures:speaker_room", args=[session.room_code])
        self.assertEqual(self.client.get(url).status_code, 302)  # giriş sayfasına
        get_user_model().objects.create_user("baska", password="parola-123")
        self.client.login(username="baska", password="parola-123")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.login(username="hoca", password="parola-123")
        self.assertContains(self.client.get(url), "Başlat")

    def test_create_session(self):
        get_user_model().objects.create_user("hoca", password="parola-123")
        self.client.login(username="hoca", password="parola-123")
        domain = Domain.objects.get(slug="bilgisayar-muhendisligi")
        resp = self.client.post(reverse("lectures:speaker_dashboard"), {"title": "Ders 1", "domain": domain.pk})
        session = LectureSession.objects.get(title="Ders 1")
        self.assertRedirects(resp, reverse("lectures:speaker_room", args=[session.room_code]))

    def test_transcript_txt(self):
        session, _ = make_session()
        services.save_final_segment(session.pk, session.domain_id, "Yığın son giren ilk çıkar.", 0, 2000)
        services.save_final_segment(session.pk, session.domain_id, "Kuyrukta ise ilk giren ilk çıkar.", 65000, 68000)
        resp = self.client.get(reverse("lectures:transcript_txt", args=[session.room_code]))
        self.assertEqual(resp["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn("attachment", resp["Content-Disposition"])
        body = resp.content.decode("utf-8-sig")
        self.assertIn("[00:00:00] Yığın son giren ilk çıkar.", body)
        self.assertIn("[00:01:05] Kuyrukta ise", body)
        self.assertIn("- kuyruk:", body)
        self.assertIn("- yığın:", body)

    def test_save_final_segment_detects_terms(self):
        session, _ = make_session()
        event = services.save_final_segment(session.pk, session.domain_id, "Algoritmanın yığına ihtiyacı var.", 0, 1)
        self.assertEqual([t["term"] for t in event["terms"]], ["algoritma", "yığın"])
        seg = TranscriptSegment.objects.get()
        self.assertEqual(seg.detected_terms.count(), 2)
        history = services.session_history(session.pk)
        self.assertEqual([t["term"] for t in history["terms"]], ["algoritma", "yığın"])
        self.assertEqual(len(history["segments"]), 1)

    def test_time_offset_continues(self):
        session, _ = make_session()
        self.assertEqual(services.next_time_offset(session.pk), 0)
        services.save_final_segment(session.pk, session.domain_id, "deneme", 0, 4000)
        self.assertEqual(services.next_time_offset(session.pk), 5000)


class WebSocketTests(TransactionTestCase):
    def setUp(self):
        call_command("loaddata", "bilgisayar_muhendisligi", verbosity=0)
        self.session, self.user = make_session()
        self.app = URLRouter(websocket_urlpatterns)

    async def test_student_receives_history_and_broadcasts(self):
        await sync_to_async(services.save_final_segment)(self.session.pk, self.session.domain_id, "Kuyruk yapısı.", 0, 900)
        comm = WebsocketCommunicator(self.app, f"/ws/ogrenci/{self.session.room_code}/")
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        history = await comm.receive_json_from()
        self.assertEqual(history["type"], "history")
        self.assertEqual(history["segments"][0]["text"], "Kuyruk yapısı.")
        self.assertEqual(history["terms"][0]["term"], "kuyruk")

        from channels.layers import get_channel_layer

        await get_channel_layer().group_send(
            self.session.group_name, {"type": "caption.event", "payload": {"type": "partial", "text": "merhaba"}}
        )
        self.assertEqual(await comm.receive_json_from(), {"type": "partial", "text": "merhaba"})
        await comm.disconnect()

    async def test_student_unknown_room(self):
        comm = WebsocketCommunicator(self.app, "/ws/ogrenci/YOKYOK/")
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        out = await comm.receive_output()
        self.assertEqual(out, {"type": "websocket.close", "code": 4404})

    async def test_speaker_requires_owner(self):
        from django.contrib.auth.models import AnonymousUser

        comm = WebsocketCommunicator(self.app, f"/ws/konusmaci/{self.session.room_code}/")
        comm.scope["user"] = AnonymousUser()
        await comm.connect()
        self.assertEqual(await comm.receive_output(), {"type": "websocket.close", "code": 4403})

        comm = WebsocketCommunicator(self.app, f"/ws/konusmaci/{self.session.room_code}/")
        comm.scope["user"] = self.user
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        self.assertEqual((await comm.receive_json_from())["type"], "history")
        await comm.disconnect()
