# make documentation

PACKAGE=$(notdir $(PWD))
LOGO="https://github.com/eudoxys/.github/blob/main/eudoxys_banner.png?raw=true"
LINK="https://www.eudoxys.com/"

all: docs test

docs: $(SOURCE)
	test -d .venv || python3 -m venv .venv
	.venv/bin/python3 -m pip install --upgrade pip
	.venv/bin/python3 -m pip install --upgrade pdoc . -r requirements.txt
	.venv/bin/pdoc $(PACKAGE)/__init__.py -o $@ --logo $(LOGO) --math --mermaid --logo-link $(LINK)

test:
	(cd ./test ; source test.sh)

.PHONY: docs test # force test to rebuild always
