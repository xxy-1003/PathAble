build-ApiFunction:
	python -m pip install -r requirements.txt -t "$(ARTIFACTS_DIR)"
	mkdir -p "$(ARTIFACTS_DIR)/fixed_camera"
	cp __init__.py app.py models.py storage.py evidence.py lambda_handler.py "$(ARTIFACTS_DIR)/fixed_camera/"
