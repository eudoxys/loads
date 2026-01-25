# make documentation

PACKAGE=loads

# valid options are --debug and --refresh
CACHE_OPTIONS=--debug

LOGO="https://github.com/eudoxys/.github/blob/main/eudoxys_banner.png?raw=true"
LINK="https://www.eudoxys.com/"

docs: $(PACKAGE)/__init__.py
	pip install --upgrade pdoc
	pdoc $< -o $@ --logo $(LOGO) --mermaid --math --logo-link $(LINK)

$(PACKAGE)/__init__.py: $(filter-out $(PACKAGE)/__init__.py,$(wildcard $(PACKAGE)/*.py))

total: 
	cd loads ; python3 total.py $(CACHE_OPTIONS)

residential: 
	cd loads ; python3 residential.py $(CACHE_OPTIONS)

commercial: 
	cd loads ; python3 commercial.py $(CACHE_OPTIONS)

industry:
	cd loads ; python3 industry.py $(CACHE_OPTIONS)

agriculture:
	cd loads ; python3 agriculture.py $(CACHE_OPTIONS)

resstock:
	cd loads ; python3 resstock.py $(CACHE_OPTIONS)

comstock:
	cd loads ; python3 comstock.py $(CACHE_OPTIONS)

calibrate:
	cd loads ; python3 calibrate.py $(CACHE_OPTIONS)

cache: total residential commercial industry agriculture resstock comstock calibrate

