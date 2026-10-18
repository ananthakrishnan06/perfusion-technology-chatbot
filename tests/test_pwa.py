import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"


def test_manifest_endpoint():
    """Verify GET /manifest.json returns valid PWA manifest matching specification."""
    res = client.get("/manifest.json")
    assert res.status_code == 200
    assert "application/manifest+json" in res.headers.get("content-type", "")

    data = res.json()
    assert data["name"] == "Perfusion AI"
    assert data["short_name"] == "Perfusion AI"
    assert data["display"] == "standalone"
    assert data["theme_color"] == "#FAF8F4"
    assert data["background_color"] == "#FAF8F4"
    assert data["start_url"] == "/"
    assert data["scope"] == "/"

    # Verify icons in manifest
    icons = data.get("icons", [])
    assert len(icons) >= 4
    sizes = [i["sizes"] for i in icons]
    assert "192x192" in sizes
    assert "512x512" in sizes
    purposes = [i.get("purpose") for i in icons]
    assert "maskable" in purposes


def test_service_worker_endpoint_and_security_policy():
    """
    Verify GET /sw.js serves valid service worker with Service-Worker-Allowed header
    and strictly forbids caching private API endpoints and chat history.
    """
    res = client.get("/sw.js")
    assert res.status_code == 200
    assert "application/javascript" in res.headers.get("content-type", "")
    assert res.headers.get("Service-Worker-Allowed") == "/"

    sw_code = res.text
    # Verify installation and cache cleanup
    assert "addEventListener('install'" in sw_code
    assert "addEventListener('activate'" in sw_code
    assert "addEventListener('fetch'" in sw_code

    # Verify security rules: API routes MUST be bypassed from CacheStorage
    assert "/api/" in sw_code
    assert "/auth" in sw_code
    assert "/chat" in sw_code
    assert "/conversations" in sw_code
    assert "isApiOrSensitiveRequest" in sw_code


def test_pwa_icons_exist_and_valid():
    """Verify that all required icon assets exist and are valid PNG images."""
    from PIL import Image

    required_icons = [
        ("icons/icon-192.png", (192, 192)),
        ("icons/icon-512.png", (512, 512)),
        ("icons/icon-maskable-192.png", (192, 192)),
        ("icons/icon-maskable-512.png", (512, 512)),
        ("icons/apple-touch-icon.png", (180, 180)),
        ("icons/favicon-32x32.png", (32, 32)),
        ("favicon.png", (32, 32)),
        ("icon-192.png", (192, 192)),
        ("icon-512.png", (512, 512)),
    ]

    for rel_path, expected_dim in required_icons:
        icon_path = frontend_dir / rel_path
        assert icon_path.exists(), f"Missing icon asset: {rel_path}"
        with Image.open(icon_path) as img:
            assert img.format == "PNG"
            assert img.size == expected_dim


def test_index_html_pwa_integration():
    """Verify index.html contains manifest links, Apple meta, and the install popup."""
    html_path = frontend_dir / "index.html"
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    # Head PWA meta tags
    assert '<link rel="manifest" href="manifest.json">' in content
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in content
    assert '<meta name="apple-mobile-web-app-title" content="Perfusion AI">' in content
    assert '<meta name="theme-color" content="#FAF8F4">' in content
    assert '<link rel="apple-touch-icon"' in content

    # Install Modal and requirements
    assert 'id="pwa-install-modal"' in content
    assert "Install Perfusion AI" in content
    assert "Install Perfusion AI for quick access to your cardiovascular knowledge assistant." in content
    assert "Install App" in content
    assert "Not Now" in content
    assert 'id="pwa-ios-instructions"' in content
    assert "Add to Home Screen" in content


def test_app_js_pwa_event_handling():
    """Verify app.js includes PWA registration, beforeinstallprompt, iOS detection, and dismissal storage."""
    app_js_path = frontend_dir / "app.js"
    assert app_js_path.exists()
    js_code = app_js_path.read_text(encoding="utf-8")

    assert "registerServiceWorker" in js_code
    assert "navigator.serviceWorker.register" in js_code
    assert "beforeinstallprompt" in js_code
    assert "deferredInstallPrompt" in js_code
    assert "triggerPwaInstall" in js_code
    assert "dismissPwaInstall" in js_code
    assert "perfusion_pwa_dismissed" in js_code
    assert "isIosSafari" in js_code
    assert "isAppInstalled" in js_code

