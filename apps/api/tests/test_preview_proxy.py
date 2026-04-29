from app.api.preview import _build_response


def test_build_response_rewrites_fastapi_docs_links_for_proxy_paths():
    proxy_result = {
        "status_code": 200,
        "headers": {"content-type": "text/html; charset=utf-8"},
        "content": b"""
        <html>
          <head></head>
          <body>
            <a href="/docs">docs</a>
            <script>
              const ui = SwaggerUIBundle({
                url: '/openapi.json',
                oauth2RedirectUrl: window.location.origin + '/docs/oauth2-redirect',
              })
            </script>
          </body>
        </html>
        """,
    }

    response = _build_response(proxy_result, "/api/preview/live/session_123", "http://127.0.0.1:41200")
    body = response.body.decode("utf-8")

    assert 'href="/api/preview/live/session_123/docs"' in body
    assert "url: '/api/preview/live/session_123/openapi.json'" in body
    assert "oauth2RedirectUrl: window.location.origin + '/api/preview/live/session_123/docs/oauth2-redirect'" in body
