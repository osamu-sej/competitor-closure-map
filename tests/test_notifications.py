import json
import unittest

from collector.notifications import pending_notifications, send_gmail_notifications


class FakeSMTP:
    def __init__(self, host, port, timeout):
        self.connection = (host, port, timeout)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def ehlo(self):
        pass

    def starttls(self, context):
        self.context = context

    def login(self, username, password):
        self.login_values = (username, password)

    def send_message(self, message):
        self.sent.append(message)


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "stores": [{
                "id": "store-1", "brand_family": "LAWSON", "canonical_name": "ローソン 横浜店",
                "address": "神奈川県横浜市中区1", "prefecture": "神奈川県", "city": "横浜市中区",
            }],
            "events": [{
                "id": "event-1", "store_id": "store-1", "status": "MISSING",
                "detected_at": "2026-10-06T00:00:00Z", "last_seen_at": "2026-10-01T00:00:00Z",
                "distance_m": 45, "nearest_seven_name": "セブン-イレブン 横浜店",
            }],
        }

    def test_only_suspected_or_confirmed_status_advances_are_notified(self):
        self.assertEqual(pending_notifications(self.state), [])

        event = self.state["events"][0]
        event.update(status="CLOSED_SUSPECTED")
        self.assertEqual(len(pending_notifications(self.state)), 1)
        event["notified_status"] = "CLOSED_SUSPECTED"
        self.assertEqual(pending_notifications(self.state), [])

        event["status"] = "CLOSED_CONFIRMED"
        self.assertEqual(len(pending_notifications(self.state)), 1)
        event["notified_status"] = "CLOSED_CONFIRMED"
        self.assertEqual(pending_notifications(self.state), [])

    def test_sends_one_digest_to_the_credential_gmail_and_removes_password_spaces(self):
        event = self.state["events"][0]
        event["status"] = "CLOSED_SUSPECTED"
        smtp = FakeSMTP("smtp.gmail.com", 587, 30)
        sent_smtp = []

        def smtp_factory(*args, **kwargs):
            sent_smtp.append(smtp)
            return smtp

        sender = send_gmail_notifications(
            pending_notifications(self.state),
            json.dumps({"email": "owner@gmail.com", "app_password": "abcd efgh"}),
            app_url="https://example.com/",
            smtp_factory=smtp_factory,
        )

        self.assertEqual(sender, "owner@gmail.com")
        self.assertEqual(sent_smtp, [smtp])
        self.assertEqual(smtp.login_values, ("owner@gmail.com", "abcdefgh"))
        message = smtp.sent[0]
        self.assertEqual(message["To"], "owner@gmail.com")
        self.assertIn("閉店の可能性", message.get_content())
        self.assertIn("ローソン 横浜店", message.get_content())
        self.assertIn("45m", message.get_content())
        self.assertIn("https://example.com/", message.get_content())

    def test_invalid_credentials_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            send_gmail_notifications([], "not-json", smtp_factory=FakeSMTP)


if __name__ == "__main__":
    unittest.main()
