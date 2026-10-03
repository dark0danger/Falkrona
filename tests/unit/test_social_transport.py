import json
from io import BytesIO
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs

from brandpilot.social import MetaConfig, MetaGraphTransport, SocialError


class Response:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return self.data


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        assert timeout == 10
        self.requests.append(request)
        return Response(next(self.responses))


class ErrorOpener:
    def __init__(self, status, provider_code):
        self.status = status
        self.provider_code = provider_code

    def open(self, request, timeout):
        body = json.dumps({"error": {"code": self.provider_code}}).encode("utf-8")
        raise HTTPError(request.full_url, self.status, "rejected", {}, BytesIO(body))


class MetaTransportTests(unittest.TestCase):
    def test_extension_keeps_secrets_in_body_and_never_assumes_permanent_lifetime(self):
        transport = MetaGraphTransport(MetaConfig("app", "app-secret", "https://example.test/callback", "v26.0"))
        opener = Opener([{"access_token": "extended", "expires_in": 5184000}])
        transport._opener = opener
        self.assertEqual(transport.extend_user_token("user-secret"), ("extended", 5184000))
        request = opener.requests[0]
        self.assertNotIn("user-secret", request.full_url)
        self.assertNotIn("app-secret", request.full_url)
        self.assertEqual(parse_qs(request.data.decode())["grant_type"], ["fb_exchange_token"])
        transport._opener = Opener([{"access_token": "extended", "expires_in": 0}])
        self.assertEqual(transport.extend_user_token("user-secret"), ("extended", 86400))
        for invalid in (False, True, -1, "invalid"):
            transport._opener = Opener([{"access_token": "extended", "expires_in": invalid}])
            with self.assertRaises(SocialError):
                transport.extend_user_token("user-secret")

    def test_photo_upload_is_unpublished_and_feed_uses_saved_photo_with_utf8_caption(self):
        transport = MetaGraphTransport(MetaConfig("fixture", "secret", "https://example.test/callback", "v26.0"))
        opener = Opener([{"id": "900"}, {"id": "12345_901"}])
        transport._opener = opener
        self.assertEqual(transport.upload_photo("12345", "private-token", b"png-bytes"), "900")
        self.assertEqual(transport.publish_photo("12345", "private-token", "900", "عصير طبيعي"), "12345_901")
        upload, publish = opener.requests
        self.assertIn(b'name="source"', upload.data)
        self.assertIn(b'name="published"\r\n\r\nfalse', upload.data)
        self.assertIn(b"png-bytes", upload.data)
        self.assertTrue(upload.get_header("Content-type").startswith("multipart/form-data; boundary="))
        fields = parse_qs(publish.data.decode("ascii"))
        self.assertEqual(fields["message"], ["عصير طبيعي"])
        self.assertEqual(json.loads(fields["attached_media[0]"][0]), {"media_fbid": "900"})
        for request in opener.requests:
            self.assertNotIn("private-token", request.full_url)
            self.assertEqual(request.get_header("Authorization"), "Bearer private-token")

    def test_reconciliation_checks_photo_story_page_and_exact_caption(self):
        transport = MetaGraphTransport(MetaConfig("fixture", "secret", "https://example.test/callback", "v26.0"))
        transport._opener = Opener([{"page_story_id": "12345_901"}, {"id": "12345_901", "message": "Approved"}])
        self.assertEqual(transport.published_photo_story("12345", "token", "900", "Approved"), "12345_901")
        transport._opener = Opener([{"page_story_id": "12345_901"}, {"id": "12345_901", "message": "Different"}])
        with self.assertRaises(SocialError):
            transport.published_photo_story("12345", "token", "900", "Approved")
        transport._opener = Opener([{"page_story_id": "99999_901"}])
        with self.assertRaises(SocialError):
            transport.published_photo_story("12345", "token", "900", "Approved")

    def setUp(self):
        self.transport = MetaGraphTransport(
            MetaConfig("fixture", "secret", "https://example.test/api/v1/social/meta/callback", "v24.0")
        )

    def test_last_page_cursor_does_not_trigger_another_request(self):
        opener = Opener([
            {
                "data": [{"id": "1234", "name": "Page", "tasks": ["PROFILE_PLUS_ANALYZE"]}],
                "paging": {"cursors": {"after": "last"}},
            }
        ])
        self.transport._opener = opener
        pages = self.transport.managed_pages("sensitive-token")
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(opener.requests), 1)
        self.assertNotIn("sensitive-token", opener.requests[0].full_url)
        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer sensitive-token")

    def test_code_exchange_binds_unknown_lifetime_without_losing_token(self):
        for response in ({"access_token": "secret-token"}, {"access_token": "secret-token", "expires_in": 0}):
            with self.subTest(response=response):
                opener = Opener([response])
                self.transport._opener = opener
                self.assertEqual(self.transport.exchange_code("fixture-code"), ("secret-token", 86400))
                self.assertEqual(opener.requests[0].get_method(), "POST")
                self.assertNotIn("secret-token", opener.requests[0].full_url)

    def test_code_exchange_accepts_numeric_lifetime_and_rejects_bad_token(self):
        for expiry, expected in (("3600", 3600), (999999999, 5184000)):
            with self.subTest(expiry=expiry):
                self.transport._opener = Opener([{"access_token": "secret-token", "expires_in": expiry}])
                self.assertEqual(self.transport.exchange_code("fixture-code"), ("secret-token", expected))
        for response in ({"expires_in": 3600}, {"access_token": "", "expires_in": 3600},
                         {"access_token": "secret-token", "expires_in": True},
                         {"access_token": "secret-token", "expires_in": "unknown"},
                         {"access_token": "secret-token", "expires_in": "9" * 1000}):
            with self.subTest(response=response):
                self.transport._opener = Opener([response])
                with self.assertRaises(SocialError) as caught:
                    self.transport.exchange_code("fixture-code")
                self.assertEqual(caught.exception.code, "provider_malformed")
                self.assertNotIn("secret-token", str(caught.exception))

    def test_post_cursor_uses_fixed_graph_host_and_stops_on_last_page(self):
        opener = Opener([
            {"data": [{"id": "1"}], "paging": {
                "next": "https://untrusted.example/redirect",
                "cursors": {"after": "next-cursor"},
            }},
            {"data": [{"id": "2"}], "paging": {"cursors": {"after": "final-cursor"}}},
        ])
        self.transport._opener = opener
        first, cursor = self.transport.post_page("1234", "sensitive-token", None)
        second, final = self.transport.post_page("1234", "sensitive-token", cursor)
        self.assertEqual((first[0]["id"], cursor, second[0]["id"], final), ("1", "next-cursor", "2", None))
        self.assertTrue(all(request.full_url.startswith("https://graph.facebook.com/v24.0/1234/posts") for request in opener.requests))
        self.assertNotIn("untrusted.example", opener.requests[1].full_url)

    def test_provider_error_codes_produce_recovery_states(self):
        for status, provider_code, expected in (
            (400, 190, "needs_reauth"),
            (400, 10, "permission_missing"),
            (400, 4, "rate_limited"),
        ):
            with self.subTest(provider_code=provider_code):
                self.transport._opener = ErrorOpener(status, provider_code)
                with self.assertRaises(SocialError) as caught:
                    self.transport.post_page("1234", "sensitive-token", None)
                self.assertEqual(caught.exception.code, expected)

    def test_engagement_preserves_zero_and_unknown_and_rejects_malformed_counts(self):
        self.transport._opener = Opener([{"reactions": {"summary": {"total_count": 0}}, "comments": {"summary": {"total_count": 4}}}])
        counts = self.transport.post_engagement("facebook_pages", "1234_1", "secret")
        self.assertEqual(counts, {"reactions": 0, "comments": 4, "shares": None})
        self.transport._opener = Opener([{"like_count": 10, "comments_count": 0}])
        self.assertEqual(self.transport.post_engagement("instagram", "5678", "secret"), {"reactions": 10, "comments": 0})
        self.transport._opener = Opener([{"reactions": []}, {"like_count": True}])
        with self.assertRaises(SocialError):
            self.transport.post_engagement("facebook_pages", "1234_1", "secret")
        with self.assertRaises(SocialError):
            self.transport.post_engagement("instagram", "5678", "secret")
        with self.assertRaises(SocialError):
            self.transport.post_engagement("facebook_pages", "../me", "secret")


if __name__ == "__main__":
    unittest.main()
