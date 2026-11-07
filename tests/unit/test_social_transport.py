import json
from datetime import datetime, timezone
from io import BytesIO
import unittest
from unittest.mock import patch
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


TOKEN_CHECK_TIME = datetime(2026, 11, 7, 16, 0, tzinfo=timezone.utc)


def debug_response(**overrides):
    metadata = {"is_valid": True, "app_id": "fixture", "type": "USER", "expires_at": 0, **overrides}
    return [{"code": 200, "body": json.dumps({"data": metadata})}]


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
        transport._opener = Opener([{"access_token": "extended", "expires_in": 0}, debug_response(app_id="app")])
        self.assertEqual(transport.extend_user_token("user-secret"), ("extended", 5184000))
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

    def test_oauth_lifetime_accepts_both_meta_duration_fields(self):
        for method in (self.transport.exchange_code, self.transport.extend_user_token):
            for key in ("expires", "expires_in"):
                for value, expected in ((5184000, 5184000), ("5183999", 5183999), (999999999, 5184000), (0, 86400)):
                    with self.subTest(method=method.__name__, key=key, value=value):
                        responses = [{"access_token": "fixture-token", key: value}]
                        if value == 0 and method.__name__ == "extend_user_token":
                            responses.append(debug_response(expires_at=int(TOKEN_CHECK_TIME.timestamp())+86400))
                        opener = Opener(responses)
                        self.transport._opener = opener
                        with patch("brandpilot.social.utc_now", return_value=TOKEN_CHECK_TIME):
                            self.assertEqual(method("fixture-input"), ("fixture-token", expected))
                        self.assertNotIn("fixture-input", opener.requests[0].full_url)
                        self.assertNotIn("secret", opener.requests[0].full_url)

    def test_oauth_lifetime_rejects_malformed_aliases_and_uses_shorter_bound(self):
        for method in (self.transport.exchange_code, self.transport.extend_user_token):
            for key in ("expires", "expires_in"):
                for invalid in (False, True, -1, 1.5, "invalid", "9" * 1000):
                    with self.subTest(method=method.__name__, key=key, invalid=invalid):
                        self.transport._opener = Opener([{"access_token": "fixture-token", key: invalid}])
                        with self.assertRaises(SocialError) as caught:
                            method("fixture-input")
                        self.assertEqual(caught.exception.code, "provider_malformed")
            for fields, expected in (({"expires_in": 3600, "expires": 5184000}, 3600),
                                     ({"expires_in": 0, "expires": 5184000}, 5184000),
                                     ({"expires_at": 9999999999}, 86400)):
                responses = [{"access_token": "fixture-token", **fields}]
                if "expires_at" in fields and method.__name__ == "extend_user_token":
                    responses.append(debug_response(expires_at=int(TOKEN_CHECK_TIME.timestamp())+86400))
                self.transport._opener = Opener(responses)
                with patch("brandpilot.social.utc_now", return_value=TOKEN_CHECK_TIME):
                    self.assertEqual(method("fixture-input"), ("fixture-token", expected))

    def test_unknown_lifetime_checks_meta_metadata_without_tokens_in_http_url(self):
        for expiry_fields in ({}, {"expires_in": 0}, {"expires": "0"}):
            with self.subTest(fields=expiry_fields):
                opener = Opener([{"access_token": "inspected-token", **expiry_fields}, debug_response()])
                self.transport._opener = opener
                self.assertEqual(self.transport.extend_user_token("user-token"), ("inspected-token", 5184000))
                inspect = opener.requests[1]
                self.assertEqual(inspect.full_url, "https://graph.facebook.com/v24.0/")
                self.assertEqual(inspect.get_method(), "POST")
                self.assertEqual(inspect.get_header("Authorization"), "Bearer fixture|secret")
                batch = json.loads(parse_qs(inspect.data.decode())["batch"][0])
                self.assertEqual(batch, [{"method": "GET", "relative_url": "debug_token?input_token=inspected-token"}])

    def test_verified_token_and_data_access_expiry_use_the_earliest_real_deadline(self):
        now = int(TOKEN_CHECK_TIME.timestamp())
        for fields, expected in (({"expires_at": now+7*86400}, 7*86400),
                                 ({"expires_at": 0, "data_access_expires_at": now+3*86400}, 3*86400),
                                 ({"expires_at": now+7*86400, "data_access_expires_at": now+86400}, 86400),
                                 ({"expires_at": 0, "data_access_expires_at": 0, "type": "SYSTEM_USER"}, 5184000)):
            self.transport._opener = Opener([{"access_token": "token"}, debug_response(**fields)])
            with patch("brandpilot.social.utc_now", return_value=TOKEN_CHECK_TIME):
                self.assertEqual(self.transport.extend_user_token("user"), ("token", expected))

    def test_invalid_or_unverifiable_token_metadata_never_gets_a_guessed_lifetime(self):
        for fields in ({"is_valid": False}, {"is_valid": "true"}, {"app_id": "other-app"}, {"type": "PAGE"},
                       {"expires_at": None}, {"expires_at": True}, {"expires_at": -1},
                       {"expires_at": "0"}, {"expires_at": 1}, {"data_access_expires_at": 1},
                       {"data_access_expires_at": False}, {"type": []}):
            with self.subTest(fields=fields):
                self.transport._opener = Opener([{"access_token": "token"}, debug_response(**fields)])
                with self.assertRaises(SocialError):
                    self.transport.extend_user_token("user")
        for response in ([], [None], [{"code": 200, "body": "bad-json"}],
                         [{"code": 200, "body": "{}"}], [{"code": 400, "body": '{"error":{"code":190}}'}],
                         [{"code": 429, "body": '{"error":{"code":4}}'}]):
            with self.subTest(response=response):
                self.transport._opener = Opener([{"access_token": "token"}, response])
                with self.assertRaises(SocialError) as caught:
                    self.transport.extend_user_token("user")
                self.assertNotIn("inspected-token", str(caught.exception))

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
