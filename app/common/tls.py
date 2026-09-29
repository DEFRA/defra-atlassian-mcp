import base64
import binascii
import logging
import os
import tempfile
from collections.abc import Mapping

logger = logging.getLogger(__name__)


# Custom CA Certificates are passed to services on deployment
# as base64 encoded environment variables with the prefix `TRUSTSTORE_`
def extract_all_certs(env: Mapping[str, str] = os.environ) -> dict[str, str]:
    certs: dict[str, str] = {}
    for var_name, var_value in env.items():
        if var_name.startswith("TRUSTSTORE_"):
            try:
                decoded_value = base64.b64decode(var_value)
            except binascii.Error as err:
                logger.error("Error decoding value for %s. Skipping. %s", var_name, err)
                continue
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, prefix=var_name, suffix=".pem"
            ) as tmp_file:
                tmp_file.write(decoded_value)
                certs[var_name] = tmp_file.name
                logger.info("Wrote %s to %s", var_name, tmp_file.name)
    logger.info("Loaded %d custom certificates", len(certs))
    return certs
