import io
import json

from api.evaluate_http import evaluate_application
from api.rate_limit import limiter


class Session:
    def close(self):
        pass


def call(app, user_id):
    payload = json.dumps({"url": "https://youtu.be/dQw4w9WgXcQ", "display_name": "Test"}).encode()
    captured = {}
    env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/v1/evaluate/youtube", "REMOTE_ADDR": "198.51.100.8",
           "wsgi.input": io.BytesIO(payload), "CONTENT_LENGTH": str(len(payload)), "HTTP_AUTHORIZATION": "Bearer test"}
    import api.evaluate_http as mod
    mod.authenticate = lambda _authorization: type("I", (), {"user_id": user_id})()
    mod.evaluate_youtube_url = lambda *args: type("R", (), {"as_dict": lambda self: {"ok": True}})()
    body = app(env, lambda status, headers: captured.update(status=status, headers=dict(headers)))
    return captured, json.loads(body[0])


def test_evaluate_rate_limit_per_user():
    limiter.reset()
    app = evaluate_application(lambda: Session())
    for _ in range(30):
        captured, _ = call(app, 42)
        assert captured["status"] == "200 OK"
    captured, _ = call(app, 42)
    assert captured["status"] == "429 Too Many Requests"
    limiter.reset()
