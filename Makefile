.PHONY: run test
run:
	python3 -m jobpilot
test:
	python3 -m unittest discover -s tests -v
	node --test tests/*.test.js
