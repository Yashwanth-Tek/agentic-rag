import json

from tests.agent.kb import METRICS_CSV, POLICY_MD
from tests.fakes import Answer, ToolCalls, make_docx, make_pdf, scripted_claude


def test_upload_processes_and_exposes_structure(make_client, upload):
    client = make_client()
    csv = upload(client, "metrics.csv", METRICS_CSV)
    assert csv["status"] == "ready" and csv["section_count"] == 3 and csv["chunk_count"] == 1
    assert csv["metadata"]["columns"] == ["Department", "Month", "Readmission rate"]
    assert csv["embedding_model"] == "fake/bag-of-words"

    md = upload(client, "policy.md", POLICY_MD)
    assert md["section_count"] == 2  # "Quality policy" has no body of its own: Targets, Scope
    assert md["metadata"]["outline"][0] == "Quality policy"

    pdf = upload(client, "handbook.pdf", make_pdf(["One.", "Two."]))
    assert pdf["metadata"]["pages"] == 2

    docx = upload(client, "benefits.docx", make_docx([("h1", "Benefits"), ("p", "Text.")]))
    assert docx["metadata"]["outline"] == ["Benefits"]

    listed = client.get("/api/documents").json()
    assert {d["filename"] for d in listed} == {
        "metrics.csv",
        "policy.md",
        "handbook.pdf",
        "benefits.docx",
    }
    assert client.get(f"/api/documents/{csv['id']}").json()["filename"] == "metrics.csv"


def test_duplicate_unsupported_and_malformed_uploads(make_client, upload):
    client = make_client()
    upload(client, "policy.md", POLICY_MD)
    duplicate = client.post("/api/documents", files={"file": ("copy.md", POLICY_MD)})
    assert (
        duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "DUPLICATE_DOCUMENT"
    )

    assert client.post("/api/documents", files={"file": ("x.exe", b"x")}).status_code == 415
    assert client.post("/api/documents", files={"file": ("x.pdf", b"nope")}).status_code == 415

    broken_pdf = upload(client, "broken.pdf", b"%PDF-1.4 but not really a pdf")
    assert broken_pdf["status"] == "failed" and "couldn't be read" in broken_pdf["error_message"]
    blank_pdf = upload(client, "blank.pdf", make_pdf(["", ""]))
    assert blank_pdf["status"] == "failed" and "Scanned" in blank_pdf["error_message"]
    bad_json = upload(client, "bad.json", b"{oops")
    assert bad_json["status"] == "failed" and "valid JSON" in bad_json["error_message"]
    assert "sha" not in json.dumps(bad_json).lower()


def test_failed_documents_are_not_searchable_by_the_agent(make_client, upload, ask):
    llm = scripted_claude([ToolCalls([("list_documents", {})]), Answer([("x", [])])])
    client = make_client(llm=llm, search_min_similarity=0.2)
    upload(client, "policy.md", POLICY_MD)
    upload(client, "broken.pdf", b"%PDF-1.4 garbage")

    ask(client, "q")

    request = llm.script.agent_requests[1]
    user = request["messages"][-1]
    [result] = user["content"]
    entries = json.loads(result["content"].split("\n")[0])
    by_name = {e["name"]: e for e in entries}
    assert by_name["broken.pdf"]["status"] == "failed" and not by_name["broken.pdf"]["searchable"]
    assert by_name["policy.md"]["searchable"]
    assert "error_message" not in by_name["broken.pdf"]


def test_delete_removes_sections_and_chunks(make_client, upload, repo):
    client = make_client()
    document = upload(client, "policy.md", POLICY_MD)
    assert client.delete(f"/api/documents/{document['id']}").status_code == 204
    assert client.delete(f"/api/documents/{document['id']}").status_code == 404
    with repo.pool.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM sections").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM chunks").fetchone()["n"] == 0


def test_health_reports_services_and_non_secret_configuration(make_client):
    client = make_client(max_tool_calls=5)
    body = client.get("/api/health").json()
    assert body["services"]["database"]["ok"]
    assert body["services"]["embedding"]["ok"]
    assert body["services"]["llm"]["ok"]
    assert body["configuration"]["limits"]["max_tool_calls"] == 5
    assert "key" not in json.dumps(body).lower()
