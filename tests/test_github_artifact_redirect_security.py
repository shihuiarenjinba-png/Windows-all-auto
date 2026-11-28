import unittest
from email.message import Message
from urllib.request import Request

from scripts.github_artifact_custody import _SafeCrossOriginRedirectHandler


class RedirectCredentialTests(unittest.TestCase):
    def setUp(self):
        self.handler = _SafeCrossOriginRedirectHandler()
        self.request = Request(
            "https://api.github.com/repos/owner/repo/actions/artifacts/123/zip",
            headers={
                "Authorization": "Bearer test-token",
                "Proxy-Authorization": "Basic test-proxy",
                "Cookie": "session=test",
                "Accept": "application/vnd.github+json",
            },
        )

    def redirect(self, target):
        return self.handler.redirect_request(
            self.request, None, 302, "Found", Message(), target
        )

    def test_cross_origin_https_redirect_strips_all_credentials(self):
        redirected = self.redirect("https://artifact-storage.example/signed.zip")
        self.assertIsNotNone(redirected)
        for header in ("Authorization", "Proxy-Authorization", "Cookie"):
            self.assertIsNone(redirected.get_header(header))
        self.assertEqual(redirected.get_header("Accept"), "application/vnd.github+json")

    def test_same_origin_https_redirect_keeps_api_authorization(self):
        redirected = self.redirect("https://api.github.com/repos/owner/repo/next")
        self.assertIsNotNone(redirected)
        self.assertEqual(redirected.get_header("Authorization"), "Bearer test-token")

    def test_https_downgrade_redirect_is_rejected(self):
        self.assertIsNone(self.redirect("http://api.github.com/repos/owner/repo/next"))


if __name__ == "__main__":
    unittest.main()
