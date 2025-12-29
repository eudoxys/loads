# make documentation

PACKAGE=loads

LOGO="https://github.com/eudoxys/.github/blob/main/eudoxys_banner.png?raw=true"
LINK="https://www.eudoxys.com/"

docs: $(PACKAGE)/__init__.py
	pip install --upgrade pdoc
	pdoc $< -o $@ --logo $(LOGO) --mermaid --math --logo-link $(LINK)
