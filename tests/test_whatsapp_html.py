import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "whatsapp_html.py"
SPEC = importlib.util.spec_from_file_location("whatsapp_html", MODULE_PATH)
assert SPEC and SPEC.loader
whatsapp_html = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = whatsapp_html
SPEC.loader.exec_module(whatsapp_html)


class WhatsAppHtmlTests(unittest.TestCase):
    def test_parse_export_reads_dates_and_participants(self):
        content = "\n".join(
            [
                "01/07/2026, 09:00 - Fabio: Primeira mensagem",
                "05/07/2026, 10:30 - Carlos: Mensagem intermediária",
                "07/07/2026, 18:45 - Fabio: Última mensagem",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "conversa.txt"
            export_path.write_text(content, encoding="utf-8")
            messages = whatsapp_html.parse_export(export_path)

        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0].timestamp, "2026-07-01T09:00:00")
        self.assertEqual(messages[1].sender, "Carlos")
        self.assertEqual(messages[2].display_date, "07/07/2026 18:45")

    def test_generated_html_contains_inclusive_date_filter(self):
        messages = [
            whatsapp_html.Message(
                timestamp="2026-07-05T10:30:00",
                display_date="05/07/2026 10:30",
                sender="Carlos",
                text="Mensagem",
                is_system=False,
                index=0,
            )
        ]

        generated = whatsapp_html.build_html(messages, "Teste", me="Fabio")

        self.assertIn('id="dateFrom"', generated)
        self.assertIn('id="dateTo"', generated)
        self.assertIn('id="clearDatesButton"', generated)
        self.assertIn("day >= dateFrom", generated)
        self.assertIn("day <= dateTo", generated)
        self.assertIn("loadDateLimits();", generated)

    def test_attachment_url_is_relative_to_html_output(self):
        content = "\n".join(
            [
                "06/05/2026 21:09 - Rodrigo Lira: "
                "\u200eIMG-20260506-WA0032.jpg (arquivo anexado)",
                "1.000$✅",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_dir = root / "exportacao"
            output_dir = root / "html"
            export_dir.mkdir()
            output_dir.mkdir()
            export_path = export_dir / "conversa.txt"
            export_path.write_text(content, encoding="utf-8")
            (export_dir / "IMG-20260506-WA0032.jpg").write_bytes(b"imagem")

            messages = whatsapp_html.parse_export(
                export_path,
                output_dir=output_dir,
            )

        self.assertEqual(messages[0].attachment_name, "IMG-20260506-WA0032.jpg")
        self.assertEqual(messages[0].sender, "Rodrigo Lira")
        self.assertFalse(messages[0].is_system)
        self.assertIn("1.000$✅", messages[0].text)
        self.assertEqual(
            messages[0].attachment_url,
            "../exportacao/IMG-20260506-WA0032.jpg",
        )

    def test_attachment_is_found_in_media_subdirectory(self):
        content = (
            "07/07/2026 06:27 - Carlos: "
            "VID-20260707-WA0000.mp4 (arquivo anexado)"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_path = root / "conversa.txt"
            media_dir = root / "midias" / "videos"
            media_dir.mkdir(parents=True)
            export_path.write_text(content, encoding="utf-8")
            (media_dir / "VID-20260707-WA0000.mp4").write_bytes(b"video")

            messages = whatsapp_html.parse_export(
                export_path,
                media_dir=root / "midias",
                output_dir=root,
            )

        self.assertEqual(
            messages[0].attachment_url,
            "midias/videos/VID-20260707-WA0000.mp4",
        )


if __name__ == "__main__":
    unittest.main()
