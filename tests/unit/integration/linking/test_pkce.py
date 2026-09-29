from app.integration.linking import pkce

# RFC 7636 Appendix B's worked example.
_RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
_RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


class TestDeriveCodeChallenge:
    def test_matches_the_rfc_7636_worked_example(self) -> None:
        assert pkce.derive_code_challenge(_RFC_VERIFIER) == _RFC_CHALLENGE

    def test_is_deterministic(self) -> None:
        verifier = pkce.generate_code_verifier()
        assert pkce.derive_code_challenge(verifier) == pkce.derive_code_challenge(
            verifier
        )


class TestGenerateCodeVerifier:
    def test_returns_a_distinct_value_each_time(self) -> None:
        assert pkce.generate_code_verifier() != pkce.generate_code_verifier()
