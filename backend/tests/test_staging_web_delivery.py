from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _nginx_configuration() -> str:
    return (REPOSITORY_ROOT / "deploy" / "staging" / "nginx-staging.conf").read_text(
        encoding="utf-8"
    )


def test_staging_nginx_serves_frontend_without_the_api_process() -> None:
    configuration = _nginx_configuration()

    assert "root /opt/socialpilot-staging/current/frontend-dist;" in configuration
    assets = configuration.split("location ^~ /assets/ {", 1)[1].split("}", 1)[0]
    spa = configuration.split("location / {", 1)[1].split("}", 1)[0]

    assert "try_files $uri =404;" in assets
    assert "expires 1y;" in assets
    assert "proxy_pass" not in assets
    assert "try_files $uri $uri/ /index.html;" in spa
    assert "proxy_pass" not in spa


def test_staging_nginx_keeps_api_behind_the_hardened_proxy() -> None:
    configuration = _nginx_configuration()

    api = configuration.split("location ^~ /api/ {", 1)[1].split("}", 1)[0]
    assert "limit_req zone=socialpilot_api" in api
    assert "proxy_pass http://127.0.0.1:8081;" in api
    assert "proxy_connect_timeout 5s;" in configuration
    assert "proxy_read_timeout 180s;" in configuration
