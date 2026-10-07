Load Testing
------------

To run tests do the following

	python3 -m venv .venv
	. .venv/bin/activate
	python3 -m pip install --upgrade pip
	pip install -r ../../requirements.txt pytest
	pytest test_*.py
