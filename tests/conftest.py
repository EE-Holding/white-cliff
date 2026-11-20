import os

import white_cliff.i18n as i18n

# The release build ships with German off. The suite keeps the reviewed path on.
i18n.GERMAN_REVIEWED = True

os.environ.setdefault("WHITE_CLIFF_USER_AGENT", "Example Name name@example.com")
os.environ.setdefault("WHITE_CLIFF_CONFIG", "/nonexistent/white-cliff-config.toml")
