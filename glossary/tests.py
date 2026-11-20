from django.core.management import call_command
from django.test import TestCase

from .matcher import SUFFIX_RE, find_terms, build_patterns, match_domain_terms, tokenize, tr_lower
from .models import Domain, Term
from .video import video_embed


class TurkishTextTests(TestCase):
    def test_tr_lower(self):
        self.assertEqual(tr_lower("IŞIK İĞNE"), "ışık iğne")
        self.assertEqual(tr_lower("Kâğıt"), "kağıt")

    def test_tokenize_keeps_offsets_and_apostrophes(self):
        text = "Linux'un çekirdeği, CPU."
        toks = tokenize(text)
        self.assertEqual([t.norm for t in toks], ["linuxun", "çekirdeği", "cpu"])
        self.assertEqual(text[toks[0].start : toks[0].end], "Linux'un")

    def test_suffix_regex(self):
        for ok in ["nın", "lar", "ları", "da", "ndan", "taki", "e", "yla", "dır", "lerinde"]:
            self.assertTrue(SUFFIX_RE.fullmatch(ok), ok)
        for bad in ["k", "mek", "sel", "n"]:
            self.assertIsNone(SUFFIX_RE.fullmatch(bad), bad)


class MatcherTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("loaddata", "bilgisayar_muhendisligi", verbosity=0)
        cls.domain = Domain.objects.get(slug="bilgisayar-muhendisligi")

    def found(self, text):
        ids = match_domain_terms(text, self.domain.pk).term_ids
        names = dict(Term.objects.filter(pk__in=ids).values_list("pk", "term"))
        return [names[i] for i in ids]

    def test_inflected_forms(self):
        cases = {
            "Algoritmanın adımlarını yazalım.": ["algoritma"],
            "Yığına eleman ekleyip kuyruktaki elemanı çıkarıyoruz.": ["yığın", "kuyruk"],
            "Derleyicinin ürettiği kodu işlemcide çalıştırırız.": ["derleyici", "işlemci"],
            "Veriler önbelleğe alınır.": ["önbellek"],
            "Kuyruğa ekle, yığından çıkar.": ["kuyruk", "yığın"],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.found(text), expected)

    def test_multiword_terms_and_compound_suffixes(self):
        self.assertEqual(self.found("Bugün ikili arama ağaçlarında ekleme yapacağız."), ["ikili arama ağacı"])
        self.assertEqual(self.found("İş parçacıkları arasında kilitlenme olur."), ["iş parçacığı", "kilitlenme"])
        self.assertEqual(self.found("Hash tablosunda çakışma olabilir."), ["hash tablosu"])
        self.assertEqual(self.found("zaman karmaşıklığını hesaplayalım"), ["zaman karmaşıklığı"])
        self.assertEqual(self.found("yapay sinir ağları"), ["yapay sinir ağı"])

    def test_longest_match_wins(self):
        # "ikili arama ağacı" içindeki "ikili arama" ayrıca sayılmamalı
        self.assertEqual(self.found("ikili arama ağacı"), ["ikili arama ağacı"])
        self.assertEqual(self.found("sanal bellek"), ["sanal bellek"])

    def test_aliases(self):
        self.assertEqual(self.found("Buna İngilizcede deadlock denir."), ["kilitlenme"])
        self.assertEqual(self.found("Stack ve queue yapıları"), ["yığın", "kuyruk"])

    def test_fuzzy_misrecognition(self):
        self.assertEqual(self.found("Algoritimanın karmaşıklığı"), ["algoritma"])

    def test_no_false_positives(self):
        self.assertEqual(self.found("Dizin yapısını inceleyelim."), [])
        self.assertEqual(self.found("Bugün ekleme işlemini göreceğiz."), [])
        self.assertEqual(self.found("Çocuklar oyuncakları yığdı."), [])

    def test_spans_point_to_original_text(self):
        text = "İkili arama ağacında arama yapalım."
        result = match_domain_terms(text, self.domain.pk)
        self.assertEqual([text[a:b] for a, b, _ in result.spans], ["İkili arama ağacında"])

    def test_index_invalidated_on_term_change(self):
        self.assertEqual(self.found("Bir trie kullanalım."), [])
        Term.objects.create(domain=self.domain, term="trie", aliases=["önek ağacı"], simple_definition="…")
        self.assertEqual(self.found("Bir trie kullanalım."), ["trie"])

    def test_build_patterns_standalone(self):
        term = Term(pk=999, domain=self.domain, term="graf", aliases=["çizge"])
        patterns = build_patterns([term])
        self.assertEqual(find_terms("Çizgelerde en kısa yol", patterns).term_ids, [999])


class VideoEmbedTests(TestCase):
    def test_youtube_variants(self):
        for url in [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        ]:
            self.assertEqual(video_embed(url)["src"], "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")

    def test_file_and_empty(self):
        self.assertEqual(video_embed("https://ornek.edu.tr/tid/algoritma.mp4")["kind"], "file")
        self.assertIsNone(video_embed(""))
        self.assertIsNone(video_embed("javascript:alert(1)"))
