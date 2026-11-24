def test_member_can_read_and_download_admin_upload_without_upload_permission(
    test_client, admin_auth_headers, auth_headers, sample_perfusion_pdf_bytes
):
    upload = {"files": ("study-notes.pdf", sample_perfusion_pdf_bytes, "application/pdf")}
    for route in ("/api/v1/documents/upload", "/api/v1/admin/documents/upload"):
        assert test_client.post(route, files=upload, headers=auth_headers).status_code == 403

    response = test_client.post(
        "/api/v1/admin/documents/upload", files=upload, headers=admin_auth_headers,
        data={"categories": '{"subject":"Bypass","module":"Filters"}'},
    )
    assert response.status_code == 200
    uploaded = response.json()[0]
    assert uploaded["processing_status"] == "indexed"
    doc = uploaded["document_id"]

    library = test_client.get("/api/v1/documents", headers=auth_headers).json()
    assert any(
        row["document_id"] == doc and row["preview_available"] and row["subject"] == "Bypass"
        for row in library["documents"]
    )
    url = f"/api/v1/documents/{doc}"
    preview = test_client.get(url + "/preview?page=2", headers=auth_headers)
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"
    download = test_client.get(url + "/download", headers=auth_headers)
    assert download.content == sample_perfusion_pdf_bytes
    assert download.headers["content-disposition"] == 'attachment; filename="study-notes.pdf"'
    assert test_client.get(url + "/download").status_code == 401
    assert test_client.get(url + "/preview").status_code == 401
    assert test_client.delete(url, headers=auth_headers).status_code == 403
    assert test_client.delete(f"/api/v1/admin/documents/{doc}", headers=admin_auth_headers).status_code == 200
    assert test_client.get(url + "/download", headers=auth_headers).status_code == 404
