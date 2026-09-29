import base64
import pathlib
import tempfile

from app.common import tls


class TestExtractAllCerts:
    def test_writes_the_decoded_bytes_to_a_real_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        encoded_cert = base64.b64encode(b"cert1").decode()

        certs = tls.extract_all_certs({"TRUSTSTORE_CERT1": encoded_cert})

        assert list(certs) == ["TRUSTSTORE_CERT1"]
        written = pathlib.Path(certs["TRUSTSTORE_CERT1"])
        assert written.parent == tmp_path
        assert written.read_bytes() == b"cert1"

    def test_invalid_base64_cert_is_skipped(self):
        certs = tls.extract_all_certs({"TRUSTSTORE_BAD": "invalid-base64!"})
        assert certs == {}

    def test_no_truststore_vars_yields_nothing(self):
        certs = tls.extract_all_certs({"NORMAL_VAR": "value"})
        assert certs == {}
