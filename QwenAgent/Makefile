.PHONY: test test-swecas test-flask test-requests test-all lint clean benchmark classify install

test-swecas:
	python -m pytest tests/test_swecas_integration.py -v

test-flask:
	cd swebench_tasks/pallets__flask-4045 && python test_blueprint.py

test-requests:
	cd swebench_tasks/psf__requests-2317 && python test_bug.py

test-all: test-swecas test-flask test-requests

benchmark:
	python benchmark/ab_runner.py

classify:
	python swebench_tasks/classify_tasks.py

lint:
	python -m py_compile core/swecas_classifier.py
	python -m py_compile core/tools_extended.py
	python -m py_compile core/qwencode_agent.py
	python -m py_compile core/cot_engine.py
	python -m py_compile swebench_tasks/classify_tasks.py
	python -m py_compile benchmark/ab_runner.py

clean:
	$(if $(filter Windows_NT,$(OS)),powershell -Command "Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force",find . -name __pycache__ -type d -exec rm -rf {} +)
	$(if $(filter Windows_NT,$(OS)),powershell -Command "Get-ChildItem -Recurse -Filter *.pyc | Remove-Item -Force",find . -name '*.pyc' -delete)

install:
	pip install -r requirements.txt
