from io import BytesIO
from pathlib import Path
import unittest
import zipfile

from docx import Document
from openpyxl import Workbook
from PIL import Image
from pypdf import PdfWriter

from brandpilot.phase3 import Phase3Error, parse_upload, validate_public_url


class Phase3SecurityTests(unittest.TestCase):
    def test_supported_media_and_sanitized_svg(self):
        png = BytesIO()
        Image.new("RGBA", (3, 2), (20, 40, 60, 128)).save(png, format="PNG")
        parsed = parse_upload("transparent.png", png.getvalue(), "image/png")
        self.assertEqual(parsed.metadata["width"], 3)
        self.assertEqual(parsed.metadata["height"], 2)

        jpeg = BytesIO()
        image = Image.new("RGB", (4, 5), "white")
        exif = Image.Exif()
        exif[274] = 6
        image.save(jpeg, format="JPEG", exif=exif)
        rotated = parse_upload("rotated.jpg", jpeg.getvalue(), "image/jpeg")
        self.assertEqual(rotated.metadata["orientation"], "6")

        webp = BytesIO()
        image.save(webp, format="WEBP")
        self.assertEqual(parse_upload("sample.webp", webp.getvalue(), "image/webp").asset_type, "image")

        safe = parse_upload("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>', "image/svg+xml")
        self.assertTrue(safe.metadata["sanitized"])
        with self.assertRaises(Phase3Error) as unsafe_svg:
            parse_upload("bad.svg", b'<svg><script>alert(1)</script></svg>', "image/svg+xml")
        self.assertEqual(unsafe_svg.exception.code, "unsafe_svg")

    def test_arabic_document_and_spreadsheet_mapping(self):
        pdf = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(pdf)
        self.assertEqual(parse_upload("brief.pdf", pdf.getvalue(), "application/pdf").asset_type, "document")

        document = Document()
        document.add_paragraph("متجر Falkrona")
        docx = BytesIO()
        document.save(docx)
        self.assertIn("Falkrona", parse_upload("brief.docx", docx.getvalue(), None).extracted_text or "")

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["اسم المنتج", "السعر", "التوفر"])
        sheet.append(["قهوة عربية", "125", "متاح"])
        xlsx = BytesIO()
        workbook.save(xlsx)
        parsed_xlsx = parse_upload("products.xlsx", xlsx.getvalue(), None)
        self.assertEqual(parsed_xlsx.product_rows[0]["name"], "قهوة عربية")
        self.assertEqual(parsed_xlsx.product_rows[0]["price"], "125")

        csv = "اسم المنتج,السعر,التوفر\nشاي,80,متاح\n".encode("utf-8")
        parsed_csv = parse_upload("products.csv", csv, "text/csv")
        self.assertEqual(parsed_csv.product_rows[0]["sku"], "شاي")

    def test_malformed_large_and_active_content_inputs_are_rejected(self):
        with self.assertRaises(Phase3Error) as invalid_image:
            parse_upload("fake.png", b"not an image", "image/png")
        self.assertEqual(invalid_image.exception.code, "invalid_image")
        with self.assertRaises(Phase3Error) as too_large:
            parse_upload("large.csv", b"x" * 11, "text/csv", max_upload_bytes=10)
        self.assertEqual(too_large.exception.code, "file_too_large")

        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr("word/document.xml", b"A" * 1_000_000)
        with self.assertRaises(Phase3Error) as bomb:
            parse_upload("unsafe.docx", archive.getvalue(), None, max_archive_bytes=2_000_000)
        self.assertEqual(bomb.exception.code, "decompression_bomb")

        with self.assertRaises(Phase3Error) as mismatch:
            parse_upload("fake.pdf", b"plain text", "application/pdf")
        self.assertEqual(mismatch.exception.code, "mime_mismatch")

    def test_url_policy_rejects_private_destinations_and_unsafe_schemes(self):
        for value in ("http://localhost/a", "http://127.0.0.1/a", "file:///tmp/a", "https://user:pass@example.com/a"):
            with self.subTest(value=value), self.assertRaises(Phase3Error):
                validate_public_url(value, resolve=False)
        with self.assertRaises(Phase3Error) as private_url:
            validate_public_url("https://public.example", resolver=lambda _host: ["10.0.0.8"])
        self.assertEqual(private_url.exception.code, "private_url")
        self.assertEqual(
            validate_public_url("https://public.example/path", resolver=lambda _host: ["93.184.216.34"]),
            "https://public.example/path",
        )


if __name__ == "__main__":
    unittest.main()
